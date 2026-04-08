from fastapi import APIRouter, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.db import get_db
from app.schemas.evaluation import EvaluationCreate, EvaluationResponse
from app.models.evaluation import EvaluationJob
from app.services.gemini_service import process_evaluation_job, job_api_keys
from app.ws_manager import manager

router = APIRouter()

@router.post("/", response_model=EvaluationResponse)
def create_evaluation(
    eval_in: EvaluationCreate, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    # Store job in database
    job = EvaluationJob(
        student_id=eval_in.student_id,
        exam_topic=eval_in.exam_topic,
        video_paths=eval_in.video_paths,
        status="pending",
        processing_mode="standard"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Temporarily store API key mapped to this job ID
    job_api_keys[job.id] = eval_in.gemini_api_key
    
    # Dispatch the background task for VLM processing
    background_tasks.add_task(process_evaluation_job, job.id, db)
    
    return job

@router.websocket("/{job_id}/ws")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(websocket, job_id)
    print("WebSocket 成功連線！", flush=True)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)
