import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import agents


VALID_SEGMENTS = {
    "agent_A": {"start": "00:00", "end": "01:00"},
    "agent_B": {"start": "00:40", "end": "02:00"},
    "agent_C": {"start": "01:40", "end": "03:00"},
    "agent_D": {"start": "02:40", "end": "04:00"},
}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("agent_D"),
        lambda value: value.update({"extra": {"start": "00:00", "end": "00:01"}}),
        lambda value: value["agent_A"].update({"extra": "value"}),
        lambda value: value["agent_A"].update({"start": "0:00"}),
        lambda value: value["agent_A"].update({"start": "00:60"}),
        lambda value: value["agent_A"].update({"start": "01:00", "end": "01:00"}),
        lambda value: value["agent_B"].update({"start": "01:01"}),
    ],
)
def test_validate_segments_rejects_invalid_schema_or_ranges(mutate):
    value = json.loads(json.dumps(VALID_SEGMENTS))
    mutate(value)
    with pytest.raises(ValueError):
        agents.validate_segments(value)


def test_validate_segments_accepts_exact_overlapping_schema():
    assert agents.validate_segments(VALID_SEGMENTS) == VALID_SEGMENTS


async def test_time_cutting_retries_one_invalid_response():
    responses = [
        SimpleNamespace(text='{"agent_A": {}}'),
        SimpleNamespace(text=json.dumps(VALID_SEGMENTS)),
    ]
    with patch(
        "app.services.agents._generate_json",
        new=AsyncMock(side_effect=responses),
    ) as generate:
        result = await agents.run_time_cutting_agent("gs://bucket/video.mp4")

    assert result == VALID_SEGMENTS
    assert generate.await_count == 2


async def test_time_cutting_fails_after_two_invalid_responses():
    with patch(
        "app.services.agents._generate_json",
        new=AsyncMock(return_value=SimpleNamespace(text="{}")),
    ) as generate:
        with pytest.raises(ValueError, match="invalid segments twice"):
            await agents.run_time_cutting_agent("gs://bucket/video.mp4")

    assert generate.await_count == 2


async def test_run_agent_uses_video_offsets_and_original_timeline_instruction():
    captured = {}

    async def fake_generate(contents, response_json_schema=None):
        captured["contents"] = contents
        return SimpleNamespace(text='[{"score": true}]')

    with patch("app.services.agents._generate_json", side_effect=fake_generate):
        result = await agents.run_agent(
            "gs://bucket/video.mp4",
            "Agent_A",
            "iv-injection",
            {"start": "01:02", "end": "03:04"},
        )

    video_part, prompt = captured["contents"]
    assert video_part.video_metadata.start_offset == "62s"
    assert video_part.video_metadata.end_offset == "184s"
    assert "original-video range 01:02 to 03:04" in prompt
    assert "do not rebase" in prompt
    assert result[0]["Agent_Name"] == "Agent_A"
    assert result[0]["Video_Path"] == "gs://bucket/video.mp4"


async def test_scoring_retries_invalid_json_once():
    with patch("app.services.agents._generate_json", new=AsyncMock(side_effect=[
        SimpleNamespace(text="not json"), SimpleNamespace(text='[{"score":1}]'),
    ])) as generate:
        result = await agents.run_agent("gs://bucket/video.mp4", "Agent_A", "exam", VALID_SEGMENTS["agent_A"])
    assert result[0]["score"] == 1
    assert generate.await_count == 2
