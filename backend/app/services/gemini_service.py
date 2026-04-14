import asyncio
from sqlalchemy.orm import Session
from app.models.evaluation import EvaluationJob, JobBranch

# Store API keys temporarily in memory for local usage, avoiding persistence in DB for safety
job_api_keys = {}

async def process_evaluation_job(job_id: str, db: Session):
    print(f"開始執行背景任務 process_evaluation_job: {job_id}", flush=True)
    api_key = job_api_keys.get(job_id)
    if not api_key:
        print(f"Error: API Key not found for job {job_id}")
        return
    
    # Fetch job from DB
    job = db.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
    if not job:
        print(f"Error: Job {job_id} not found in DB")
        return
        
    try:
        # Phase 1: Upload (Mock implementation of Gemini API Upload)
        job.status = "uploading"
        # Update specific branch to use Pub/Sub PostgreSQL notification
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_UPLOAD").update({
            "status": "in-progress",
            "message": "Starting video uploads using provided Gemini API Key..."
        })
        db.commit()
        
        for i, path in enumerate(job.video_paths):
            await asyncio.sleep(1.5) # Mocking file upload latency
            # Database Update - The changes will be pushed by DB trigger!
            db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_UPLOAD").update({
                "progress": f"{i+1}/{len(job.video_paths)}",
                "message": f"Uploaded {path} to Gemini"
            })
            db.commit()

        # Complete GEMINI_UPLOAD branch
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_UPLOAD").update({"status": "completed"})

        # Phase 2: Processing (Batch or Standard depending on user selection)
        job.status = "processing"
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_PROCESSING").update({
            "status": "in-progress",
            "message": f"Starting {job.processing_mode} mode video analysis..."
        })
        db.commit()
        
        # Simulate processing time depending on mode
        processing_time = 5 if job.processing_mode == "batch" else 3
        
        for i in range(processing_time):
            await asyncio.sleep(1)
            # Pub/Sub automatically through PostgreSQL updates
            db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_PROCESSING").update({
                "progress": f"{i+1}/{processing_time}",
                "message": f"Analyzing... (polling status)" if job.processing_mode == "batch" else f"Analyzing video {i+1}..."
            })
            db.commit()
            
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="GEMINI_PROCESSING").update({"status": "completed"})

        # Phase 3: LLM Scoring and Synthesis
        job.status = "scoring"
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="LLM_SCORING").update({
            "status": "in-progress",
            "message": "VLM analysis complete. Aggregating results with LLM..."
        })
        db.commit()
        
        await asyncio.sleep(2) # Mock scoring
        
        # Finished Phase
        job.result = {
            "passed": True, 
            "score": 90, 
            "checklist": [
                {"item": "Washed hands before procedure", "passed": True},
                {"item": "Verified patient identity", "passed": True},
                {"item": "Explained procedure to patient", "passed": False}
            ],
            "details": "Overall good execution, forgot to verbally explain procedure."
        }
        job.status = "finished"
        
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="LLM_SCORING").update({
            "status": "completed",
            "message": "Evaluation completed successfully."
        })
        db.commit()
        
        # NOTE: the frontend ws parsing might expect 'FINISHED' stage with result
        # To adapt, you can insert another branch update.
        db.query(JobBranch).filter_by(job_id=job_id, branch_name="FINISHED").update({
            "status": "completed",
            "message": "done"
        }, synchronize_session=False)  # Usually FINISHED branch isn't manually pre-created.
        
        # Because we didn't pre-create "FINISHED", let's handle the payload by creating one to trigger final update
        finished_branch = JobBranch(job_id=job_id, branch_name="FINISHED", status="completed", message="Evaluation completed successfully.")
        db.add(finished_branch)
        db.commit()

    except Exception as e:
        job.status = "failed"
        job.result = {"error": str(e)}
        db.query(JobBranch).filter_by(job_id=job_id).update({
            "status": "failed",
            "message": f"Execution failed: {str(e)}"
        })
        db.commit()
    finally:
        # Cleanup API Key from memory after job resolves
        if job_id in job_api_keys:
            del job_api_keys[job_id]
