import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import agents, gemini_service
from tests.test_agents import VALID_SEGMENTS


async def test_segmentation_reports_queue_analysis_and_retry():
    phases = []
    semaphore = asyncio.Semaphore(0)
    responses = iter(["{}", json.dumps(VALID_SEGMENTS)])

    async def generate_content(**kwargs):
        return SimpleNamespace(text=next(responses))

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=generate_content,
    )))
    queued = asyncio.Event()

    def report(phase):
        phases.append(phase)
        queued.set()

    with patch.object(agents, "_model_semaphore", semaphore), patch.object(
        agents, "get_client", return_value=client,
    ):
        task = asyncio.create_task(agents.run_time_cutting_agent("gs://test/video.mp4", report))
        try:
            await asyncio.wait_for(queued.wait(), timeout=1)
            assert phases == ["queued"]
            assert not task.done()
            semaphore.release()
            assert await asyncio.wait_for(task, timeout=1) == VALID_SEGMENTS
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert phases == ["queued", "analyzing", "retrying", "queued", "analyzing"]
    assert not semaphore.locked()


async def test_segmentation_heartbeat_keeps_completed_count_and_stops():
    updates = []
    heartbeat = asyncio.Event()

    def update(db, job_id, branch, **values):
        updates.append(values)
        if sum("analyzing" in row["message"] for row in updates) >= 2:
            heartbeat.set()

    async def segment(uri, on_progress):
        on_progress("analyzing")
        await heartbeat.wait()
        return VALID_SEGMENTS

    with patch.object(gemini_service, "_update_branch", side_effect=update), patch.object(
        agents, "run_time_cutting_agent", side_effect=segment,
    ), patch.object(gemini_service, "SEGMENT_PROGRESS_INTERVAL_SECONDS", 0.001):
        result = await asyncio.wait_for(
            gemini_service._segment_with_progress(None, "job", "gs://test/video.mp4", "0/5"),
            timeout=1,
        )
        count = len(updates)
        await asyncio.sleep(0.01)
        assert len(updates) == count

    assert result == VALID_SEGMENTS
    assert heartbeat.is_set()
    assert all(row["progress"] == "0/5" for row in updates)
    assert all("s | gs://test/video.mp4" in row["message"] for row in updates)


async def test_cancelling_progress_cancels_model_work():
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def segment(uri, on_progress):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(gemini_service, "_update_branch"), patch.object(
        agents, "run_time_cutting_agent", side_effect=segment,
    ):
        task = asyncio.create_task(gemini_service._segment_with_progress(
            None, "job", "gs://test/video.mp4", "0/5",
        ))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert cancelled.is_set()


async def test_progress_propagates_model_failure():
    async def segment(uri, on_progress):
        raise RuntimeError("model unavailable")

    with patch.object(gemini_service, "_update_branch"), patch.object(
        agents, "run_time_cutting_agent", side_effect=segment,
    ):
        with pytest.raises(RuntimeError, match="model unavailable"):
            await gemini_service._segment_with_progress(None, "job", "gs://test/video.mp4", "0/5")
