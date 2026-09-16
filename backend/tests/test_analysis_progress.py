import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import agents, gemini_service
from tests.test_agents import VALID_SEGMENTS


async def test_segmentation_reports_queue_analysis_and_retry():
    phases = []
    responses = iter(["{}", json.dumps(VALID_SEGMENTS)])

    async def generate_content(**kwargs):
        return SimpleNamespace(text=next(responses))

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=generate_content,
    )))
    with patch.object(agents, "get_client", return_value=client):
        result = await agents.run_time_cutting_agent(
            "gs://test/video.mp4", phases.append,
        )

    assert result == VALID_SEGMENTS
    assert phases == ["queued", "analyzing", "retrying", "queued", "analyzing"]


async def test_segmentation_heartbeat_keeps_completed_count_and_stops():
    updates = []
    heartbeat = asyncio.Event()
    call = SimpleNamespace(evaluation_id="job", video_id="video")

    async def publish(pool, model_call, phase, elapsed):
        updates.append((phase, elapsed))
        if len(updates) >= 3:
            heartbeat.set()
        return True

    async def segment(uri, on_progress):
        on_progress("analyzing")
        await heartbeat.wait()
        return VALID_SEGMENTS

    with patch.object(
        gemini_service.repository, "report_segment_progress", side_effect=publish,
    ), patch.object(
        agents, "run_time_cutting_agent", side_effect=segment,
    ), patch.object(gemini_service, "SEGMENT_PROGRESS_INTERVAL_SECONDS", 0.001):
        result = await asyncio.wait_for(
            gemini_service._segment_with_progress(object(), call, "gs://test/video.mp4"),
            timeout=1,
        )
        count = len(updates)
        await asyncio.sleep(0.01)

    assert result == VALID_SEGMENTS
    assert updates[0][0] == "queued"
    assert any(phase == "analyzing" for phase, _ in updates)
    assert len(updates) == count


async def test_cancelling_progress_cancels_model_work():
    started, cancelled = asyncio.Event(), asyncio.Event()
    call = SimpleNamespace(evaluation_id="job", video_id="video")

    async def segment(uri, on_progress):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(
        gemini_service.repository, "report_segment_progress", new=AsyncMock(return_value=True),
    ), patch.object(agents, "run_time_cutting_agent", side_effect=segment):
        task = asyncio.create_task(gemini_service._segment_with_progress(
            object(), call, "gs://test/video.mp4",
        ))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert cancelled.is_set()


async def test_progress_propagates_model_failure():
    call = SimpleNamespace(evaluation_id="job", video_id="video")

    async def segment(uri, on_progress):
        raise RuntimeError("model unavailable")

    with patch.object(
        gemini_service.repository, "report_segment_progress", new=AsyncMock(return_value=True),
    ), patch.object(agents, "run_time_cutting_agent", side_effect=segment):
        with pytest.raises(RuntimeError, match="model unavailable"):
            await gemini_service._segment_with_progress(
                object(), call, "gs://test/video.mp4",
            )
