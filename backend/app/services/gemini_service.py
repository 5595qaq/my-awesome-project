import asyncio
from sqlalchemy.orm import Session
from app.models.evaluation import EvaluationJob
from app.ws_manager import manager

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
        db.commit()
        await manager.broadcast_to_job("STAGE_UPDATE", {"stage": "GEMINI_UPLOAD", "message": "Starting video uploads using provided Gemini API Key..."}, job_id)
        
        for i, path in enumerate(job.video_paths):
            await asyncio.sleep(1.5) # Mocking file upload latency
            await manager.broadcast_to_job("PROGRESS_UPDATE", {
                "stage": "GEMINI_UPLOAD", 
                "progress": f"{i+1}/{len(job.video_paths)}",
                "message": f"Uploaded {path} to Gemini"
            }, job_id)

        # Phase 2: Processing (Batch or Standard depending on user selection)
        job.status = "processing"
        db.commit()
        await manager.broadcast_to_job("STAGE_UPDATE", {"stage": "GEMINI_PROCESSING", "message": f"Starting {job.processing_mode} mode video analysis..."}, job_id)
        
        # Simulate processing time depending on mode
        processing_time = 5 if job.processing_mode == "batch" else 3
        
        for i in range(processing_time):
            await asyncio.sleep(1)
            await manager.broadcast_to_job("PROGRESS_UPDATE", {
                "stage": "GEMINI_PROCESSING", 
                "progress": f"{i+1}/{processing_time}",
                "message": f"Analyzing... (polling status)" if job.processing_mode == "batch" else f"Analyzing video {i+1}..."
            }, job_id)
        
        # Phase 3: LLM Scoring and Synthesis
        job.status = "scoring"
        db.commit()
        await manager.broadcast_to_job("STAGE_UPDATE", {"stage": "LLM_SCORING", "message": "VLM analysis complete. Aggregating results with LLM..."}, job_id)
        
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
        db.commit()
        
        await manager.broadcast_to_job("STAGE_UPDATE", {
            "stage": "FINISHED", 
            "message": "Evaluation completed successfully.",
            "result": job.result
        }, job_id)

    except Exception as e:
        job.status = "failed"
        job.result = {"error": str(e)}
        db.commit()
        await manager.broadcast_to_job("STAGE_UPDATE", {"stage": "FAILED", "message": f"Execution failed: {str(e)}"}, job_id)
    finally:
        # Cleanup API Key from memory after job resolves
        if job_id in job_api_keys:
            del job_api_keys[job_id]
