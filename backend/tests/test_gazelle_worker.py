from unittest.mock import AsyncMock, patch

import pytest

from app import gazelle_worker
from app.services import evaluation_queue as repo


async def test_gaze_worker_persists_overlay_result(monkeypatch):
    call = repo.ModelCall(evaluation_id="evaluation", video_id="video", action="gaze")
    job = type("Job", (), {"payload": call.model_dump_json()})()
    video = {
        "gaze_source_uri": "gs://bucket/source_gaze_5fps.mp4",
        "segments": {"agent_A": {"start": "00:10", "end": "00:20"}},
    }
    result = {"overlay_uri": "gs://bucket/overlay.mp4", "metadata_uri": "gs://bucket/gaze.json"}
    pool = object()
    monkeypatch.setattr(repo, "prepare_call", AsyncMock(return_value=video))
    persist = AsyncMock()
    monkeypatch.setattr(repo, "persist_result", persist)
    with patch("app.services.gazelle_service.infer_overlay", return_value=result) as infer:
        await gazelle_worker.process_gaze_call(job, pool)
    infer.assert_called_once_with(
        "video", "gs://bucket/source_gaze_5fps.mp4", {"start": "00:10", "end": "00:20"},
    )
    persist.assert_awaited_once_with(pool, call, result)


async def test_gaze_worker_marks_parent_failed(monkeypatch):
    call = repo.ModelCall(evaluation_id="evaluation", video_id="video", action="gaze")
    job = type("Job", (), {"payload": call.model_dump_json()})()
    monkeypatch.setattr(repo, "prepare_call", AsyncMock(return_value={
        "gaze_source_uri": None, "segments": {"agent_A": {"start": "00:10", "end": "00:20"}},
    }))
    failure = AsyncMock()
    monkeypatch.setattr(repo, "fail_job", failure)
    with patch("app.services.gazelle_service.infer_overlay", side_effect=ValueError("missing")), \
         pytest.raises(ValueError):
        await gazelle_worker.process_gaze_call(job, object())
    failure.assert_awaited_once()
