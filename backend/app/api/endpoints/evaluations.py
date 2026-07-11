from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.db import get_db
from app.schemas.evaluation import EvaluationCreate, EvaluationResponse
from app.models.evaluation import EvaluationJob, JobBranch
from app.ws_manager import manager

router = APIRouter()

@router.get("/{job_id}", response_model=EvaluationResponse)
def get_evaluation(job_id: str, db: Session = Depends(get_db)):
    # The WebSocket only streams job_branches row changes (no result field),
    # so the frontend fetches the full job - including result - from here
    # once it observes the FINISHED branch complete.
    job = db.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.post("/", response_model=EvaluationResponse)
def create_evaluation(
    eval_in: EvaluationCreate,
    db: Session = Depends(get_db)
):
    # Store job in database
    job = EvaluationJob(
        exam_topic=eval_in.exam_topic,
        video_paths=eval_in.video_paths,
        status="pending",
        processing_mode="standard"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Pre-create branches tracking status mapping to different job parts.
    # Inserting the GEMINI_UPLOAD branch with "pending" will trigger PostgreSQL Pub/Sub.
    branches = [
        JobBranch(job_id=job.id, branch_name="GEMINI_UPLOAD", status="pending"),
        JobBranch(job_id=job.id, branch_name="GEMINI_PROCESSING", status="pending"),
        JobBranch(job_id=job.id, branch_name="LLM_SCORING", status="pending"),
    ]
    db.add_all(branches)
    db.commit()
    
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
