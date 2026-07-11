import asyncio
from sqlalchemy.orm import Session

from app.models.evaluation import EvaluationJob, JobBranch
from app.services import gcs_service, agents


async def process_evaluation_job(job_id: str, db: Session):
    print(f"開始執行背景任務 process_evaluation_job: {job_id}", flush=True)

    job = db.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
    if not job:
        print(f"Error: Job {job_id} not found in DB")
        return

    try:
        # Phase 1: videos are uploaded to GCS before the job is submitted, so
        # this just confirms each gs:// URI actually resolves.
        job.status = "uploading"
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_UPLOAD").update({
            "status": "in-progress",
            "message": "Verifying uploaded videos in GCS..."
        })
        db.commit()

        for i, video_uri in enumerate(job.video_paths):
            exists = await asyncio.to_thread(gcs_service.blob_exists_at_uri, video_uri)
            if not exists:
                raise FileNotFoundError(f"Video not found in GCS: {video_uri}")

            db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_UPLOAD").update({
                "progress": f"{i+1}/{len(job.video_paths)}",
                "message": f"Confirmed {video_uri}"
            })
            db.commit()

        db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_UPLOAD").update({"status": "completed"})
        db.commit()

        # Phase 2: run every configured agent against every video via Vertex AI.
        job.status = "processing"
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_PROCESSING").update({
            "status": "in-progress",
            "message": f"Starting {job.processing_mode} mode video analysis..."
        })
        db.commit()

        all_items = []
        total_calls = len(job.video_paths) * len(agents.AGENT_NAMES)
        call_index = 0

        for video_uri in job.video_paths:
            for agent_name in agents.AGENT_NAMES:
                items = await asyncio.to_thread(agents.run_agent, video_uri, agent_name, job.exam_topic)
                all_items.extend(items)
                call_index += 1

                db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_PROCESSING").update({
                    "progress": f"{call_index}/{total_calls}",
                    "message": f"{agent_name} finished analyzing {video_uri}"
                })
                db.commit()

        db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_PROCESSING").update({"status": "completed"})
        db.commit()

        # Phase 3: store the raw, not-yet-unified agent outputs as-is.
        job.status = "scoring"
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="LLM_SCORING").update({
            "status": "in-progress",
            "message": "Aggregating agent outputs..."
        })
        db.commit()

        job.result = {"items": all_items}
        job.status = "finished"

        db.query(JobBranch).filter_by(job_id=job_id, branch_name="LLM_SCORING").update({
            "status": "completed",
            "message": "Evaluation completed successfully."
        })
        db.commit()

        db.add(JobBranch(job_id=job_id, branch_name="FINISHED", status="completed", message="done"))
        db.commit()

    except Exception as e:
        job.status = "failed"
        job.result = {"error": str(e)}
        db.query(JobBranch).filter_by(job_id=job_id).update({
            "status": "failed",
            "message": f"Execution failed: {str(e)}"
        })
        db.commit()
