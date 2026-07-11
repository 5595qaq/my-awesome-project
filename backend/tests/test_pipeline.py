from unittest.mock import patch

from app.models.evaluation import EvaluationJob, JobBranch
from app.services import gemini_service


async def test_process_evaluation_job_completes_pipeline(db_session):
    job = EvaluationJob(
        id="pipeline-test-job",
        exam_topic="iv-injection",
        video_paths=["gs://test-bucket/cam1.mp4"],
        status="pending",
        processing_mode="standard",
    )
    db_session.add(job)
    db_session.add_all([
        JobBranch(job_id=job.id, branch_name="GEMINI_UPLOAD", status="pending"),
        JobBranch(job_id=job.id, branch_name="GEMINI_PROCESSING", status="pending"),
        JobBranch(job_id=job.id, branch_name="LLM_SCORING", status="pending"),
    ])
    db_session.commit()

    fake_item = {
        "step": "Step 1. Wash hands",
        "score": 1,
        "Video_Path": "gs://test-bucket/cam1.mp4",
        "Agent_Name": "Agent_B",
    }

    with patch("app.services.gemini_service.gcs_service.blob_exists_at_uri", return_value=True), \
         patch("app.services.gemini_service.agents.run_agent", return_value=[fake_item]):
        await gemini_service.process_evaluation_job(job.id, db_session)

    db_session.refresh(job)
    assert job.status == "finished"
    assert job.result["items"][0]["step"] == "Step 1. Wash hands"

    branches = {
        b.branch_name: b.status
        for b in db_session.query(JobBranch).filter_by(job_id=job.id).all()
    }
    assert branches["GEMINI_UPLOAD"] == "completed"
    assert branches["GEMINI_PROCESSING"] == "completed"
    assert branches["LLM_SCORING"] == "completed"
    assert branches["FINISHED"] == "completed"


async def test_process_evaluation_job_marks_failed_when_video_missing(db_session):
    job = EvaluationJob(
        id="pipeline-test-job-missing",
        exam_topic="iv-injection",
        video_paths=["gs://test-bucket/missing.mp4"],
        status="pending",
        processing_mode="standard",
    )
    db_session.add(job)
    db_session.add_all([
        JobBranch(job_id=job.id, branch_name="GEMINI_UPLOAD", status="pending"),
        JobBranch(job_id=job.id, branch_name="GEMINI_PROCESSING", status="pending"),
        JobBranch(job_id=job.id, branch_name="LLM_SCORING", status="pending"),
    ])
    db_session.commit()

    with patch("app.services.gemini_service.gcs_service.blob_exists_at_uri", return_value=False):
        await gemini_service.process_evaluation_job(job.id, db_session)

    db_session.refresh(job)
    assert job.status == "failed"
    assert "error" in job.result
