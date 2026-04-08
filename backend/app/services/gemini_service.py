import asyncio
from sqlalchemy.orm import Session
from app.models.evaluation import EvaluationJob
from app.ws_manager import manager
# 關鍵：匯入你剛建立的中控調度器
from app.services.orchestrator import orchestrator

# Store API keys temporarily in memory for local usage
job_api_keys = {}

async def process_evaluation_job(job_id: str, db: Session):
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
        # --- Phase 1: Upload (保持原本的模擬邏輯) ---
        job.status = "uploading"
        db.commit()
        await manager.broadcast_to_job("STAGE_UPDATE", {"stage": "GEMINI_UPLOAD", "message": "Starting video uploads using provided Gemini API Key..."}, job_id)
        
        for i, path in enumerate(job.video_paths):
            await asyncio.sleep(1.5) 
            await manager.broadcast_to_job("PROGRESS_UPDATE", {
                "stage": "GEMINI_UPLOAD", 
                "progress": f"{i+1}/{len(job.video_paths)}",
                "message": f"Uploaded {path} to Gemini"
            }, job_id)

        # --- Phase 2: Processing (保持原本的模擬邏輯) ---
        job.status = "processing"
        db.commit()
        await manager.broadcast_to_job("STAGE_UPDATE", {"stage": "GEMINI_PROCESSING", "message": f"Starting {job.processing_mode} mode video analysis..."}, job_id)
        
        processing_time = 5 if job.processing_mode == "batch" else 3
        for i in range(processing_time):
            await asyncio.sleep(1)
            await manager.broadcast_to_job("PROGRESS_UPDATE", {
                "stage": "GEMINI_PROCESSING", 
                "progress": f"{i+1}/{processing_time}",
                "message": f"Analyzing... (polling status)" if job.processing_mode == "batch" else f"Analyzing video {i+1}..."
            }, job_id)
        
        # --- Phase 3: LLM Scoring and Synthesis (改為呼叫 Orchestrator) ---
        job.status = "scoring"
        db.commit()
        await manager.broadcast_to_job("STAGE_UPDATE", {
            "stage": "LLM_SCORING", 
            "message": "VLM 分析完成，正在調度 Agent 進行多維度評分..."
        }, job_id)
        
        # 這裡會進入 orchestrator.py，然後再進入 agent_d.py
        # 我們把前端傳來的考試題目 (job.exam_topic) 傳進去
        final_result = await orchestrator.run_evaluation(
            exam_type=job.exam_topic, 
            video_paths=job.video_paths, 
            api_key=api_key, 
            job_id=job_id
        )
        
        # --- Finished Phase: 儲存來自 Orchestrator 的結果 ---
        job.result = final_result
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
        # Cleanup API Key from memory
        if job_id in job_api_keys:
            del job_api_keys[job_id]
