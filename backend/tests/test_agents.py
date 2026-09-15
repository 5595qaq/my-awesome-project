import asyncio
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
        lambda value: value["agent_D"].update({"end": "02:50"}),
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
    truncated_agent_d = json.loads(json.dumps(VALID_SEGMENTS))
    truncated_agent_d["agent_D"]["end"] = "02:50"
    responses = [
        SimpleNamespace(text=json.dumps(truncated_agent_d)),
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


async def test_model_calls_share_a_four_request_process_limit():
    active = 0
    max_active = 0
    release = asyncio.Event()

    class FakeModels:
        async def generate_content(self, **kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            if max_active == 4:
                release.set()
            await asyncio.wait_for(release.wait(), timeout=1)
            await asyncio.sleep(0.001)
            active -= 1
            return SimpleNamespace(text="{}")

    fake_client = SimpleNamespace(aio=SimpleNamespace(models=FakeModels()))
    with patch("app.services.agents.get_client", return_value=fake_client):
        await asyncio.gather(
            *(agents._generate_json([f"request-{index}"]) for index in range(8))
        )

    assert max_active == 4
