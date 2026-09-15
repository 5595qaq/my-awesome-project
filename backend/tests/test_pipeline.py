import asyncio
from unittest.mock import AsyncMock, patch

from app.models.evaluation import EvaluationJob, JobBranch
from app.services import agents, gemini_service


SEGMENTS = {
    "agent_A": {"start": "00:00", "end": "01:00"},
    "agent_B": {"start": "00:40", "end": "02:00"},
    "agent_C": {"start": "01:40", "end": "03:00"},
    "agent_D": {"start": "02:40", "end": "04:00"},
}


def _add_job(
    db_session,
    job_id: str,
    video_path: str | list[str] = "gs://test-bucket/cam1.mp4",
):
    video_paths = [video_path] if isinstance(video_path, str) else video_path
    job = EvaluationJob(
        id=job_id,
        exam_topic="iv-injection",
        video_paths=video_paths,
        status="pending",
        processing_mode="standard",
    )
    db_session.add(job)
    db_session.add_all(
        [
            JobBranch(job_id=job.id, branch_name="GEMINI_UPLOAD", status="pending"),
            JobBranch(job_id=job.id, branch_name="GEMINI_PROCESSING", status="pending"),
            JobBranch(job_id=job.id, branch_name="LLM_SCORING", status="pending"),
        ]
    )
    db_session.commit()
    return job


async def test_process_evaluation_job_segments_then_runs_four_agents_in_parallel(db_session):
    video_uri = "gs://test-bucket/cam1.mp4"
    job = _add_job(db_session, "pipeline-test-job", video_uri)
    started: set[str] = set()
    all_started = asyncio.Event()
    active = 0
    max_active = 0

    async def fake_run_agent(uri, agent_name, exam_topic, segment):
        nonlocal active, max_active
        assert uri == video_uri
        assert exam_topic == "iv-injection"
        assert segment == SEGMENTS[agents.AGENT_SEGMENT_KEYS[agent_name]]
        started.add(agent_name)
        active += 1
        max_active = max(max_active, active)
        if len(started) == 4:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1)
        # Deliberately finish in reverse order.
        await asyncio.sleep((4 - agents.AGENT_NAMES.index(agent_name)) * 0.001)
        active -= 1
        return [{
            "step": agent_name,
            "score": 1,
            "Video_Path": uri,
            "Agent_Name": agent_name,
        }]

    with patch(
        "app.services.gemini_service.gcs_service.blob_exists_at_uri", return_value=True
    ), patch(
        "app.services.gemini_service.agents.run_time_cutting_agent",
        new=AsyncMock(return_value=SEGMENTS),
    ) as time_cutting, patch(
        "app.services.gemini_service.agents.run_agent", side_effect=fake_run_agent
    ):
        await gemini_service.process_evaluation_job(job.id, db_session)

    db_session.refresh(job)
    assert max_active == 4
    assert started == set(agents.AGENT_NAMES)
    time_cutting.assert_awaited_once_with(video_uri)
    assert job.status == "finished"
    assert job.result["segments"] == {video_uri: SEGMENTS}
    assert [item["Agent_Name"] for item in job.result["items"]] == agents.AGENT_NAMES
    assert [item["Video_Path"] for item in job.result["items"]] == [video_uri] * 4

    branches = {
        branch.branch_name: branch.status
        for branch in db_session.query(JobBranch).filter_by(job_id=job.id).all()
    }
    assert branches == {
        "GEMINI_UPLOAD": "completed",
        "GEMINI_PROCESSING": "completed",
        "LLM_SCORING": "completed",
        "FINISHED": "completed",
    }


async def test_process_evaluation_job_preserves_segments_for_multiple_videos(db_session):
    video_uris = ["gs://test-bucket/cam1.mp4", "gs://test-bucket/cam2.mp4"]
    job = _add_job(db_session, "pipeline-test-job-multiple-videos", video_uris)

    async def fake_run_agent(uri, agent_name, exam_topic, segment):
        return [{"Agent_Name": agent_name, "Video_Path": uri}]

    with patch(
        "app.services.gemini_service.gcs_service.blob_exists_at_uri", return_value=True
    ), patch(
        "app.services.gemini_service.agents.run_time_cutting_agent",
        new=AsyncMock(return_value=SEGMENTS),
    ) as time_cutting, patch(
        "app.services.gemini_service.agents.run_agent", side_effect=fake_run_agent
    ):
        await gemini_service.process_evaluation_job(job.id, db_session)

    db_session.refresh(job)
    assert job.result["segments"] == {uri: SEGMENTS for uri in video_uris}
    assert [call.args[0] for call in time_cutting.await_args_list] == video_uris
    assert [item["Video_Path"] for item in job.result["items"]] == [
        uri for uri in video_uris for _ in agents.AGENT_NAMES
    ]


async def test_process_evaluation_job_cancels_sibling_agents_on_failure(db_session):
    job = _add_job(db_session, "pipeline-test-job-agent-failure")
    all_started = asyncio.Event()
    started: set[str] = set()
    cancelled: set[str] = set()

    async def fake_run_agent(uri, agent_name, exam_topic, segment):
        started.add(agent_name)
        if len(started) == 4:
            all_started.set()
        await all_started.wait()
        if agent_name == "Agent_A":
            raise RuntimeError("agent failed")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.add(agent_name)
            raise

    with patch(
        "app.services.gemini_service.gcs_service.blob_exists_at_uri", return_value=True
    ), patch(
        "app.services.gemini_service.agents.run_time_cutting_agent",
        new=AsyncMock(return_value=SEGMENTS),
    ), patch("app.services.gemini_service.agents.run_agent", side_effect=fake_run_agent):
        await gemini_service.process_evaluation_job(job.id, db_session)

    db_session.refresh(job)
    assert job.status == "failed"
    assert "agent failed" in job.result["error"]
    assert cancelled == {"Agent_B", "Agent_C", "Agent_D"}


async def test_process_evaluation_job_marks_failed_when_segmentation_fails(db_session):
    job = _add_job(db_session, "pipeline-test-job-segmentation-failure")

    with patch(
        "app.services.gemini_service.gcs_service.blob_exists_at_uri", return_value=True
    ), patch(
        "app.services.gemini_service.agents.run_time_cutting_agent",
        new=AsyncMock(side_effect=ValueError("invalid segments")),
    ), patch(
        "app.services.gemini_service.agents.run_agent", new=AsyncMock()
    ) as run_agent:
        await gemini_service.process_evaluation_job(job.id, db_session)

    db_session.refresh(job)
    assert job.status == "failed"
    assert "invalid segments" in job.result["error"]
    run_agent.assert_not_awaited()


async def test_process_evaluation_job_marks_failed_when_video_missing(db_session):
    job = _add_job(
        db_session,
        "pipeline-test-job-missing",
        "gs://test-bucket/missing.mp4",
    )

    with patch(
        "app.services.gemini_service.gcs_service.blob_exists_at_uri", return_value=False
    ):
        await gemini_service.process_evaluation_job(job.id, db_session)

    db_session.refresh(job)
    assert job.status == "failed"
    assert "error" in job.result
