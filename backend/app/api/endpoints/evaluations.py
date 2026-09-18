from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from sqlalchemy.orm import Session
from app.db import get_db
from app.schemas.evaluation import EvaluationCreate, EvaluationResponse
from app.models.evaluation import EvaluationJob
from app.ws_manager import manager
from app.services import evaluation_queue

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
async def create_evaluation(
    eval_in: EvaluationCreate,
    request: Request,
):
    async with request.app.state.queue_pool.acquire() as connection:
        return await evaluation_queue.create_evaluation(connection, eval_in.exam_topic, eval_in.video_paths)


@router.post("/{job_id}/retry", response_model=EvaluationResponse)
async def retry_evaluation(job_id: str, request: Request):
    try:
        return await evaluation_queue.retry_evaluation(request.app.state.queue_pool, job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

@router.websocket("/{job_id}/ws")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(websocket, job_id)
    print("WebSocket 成功連線！", flush=True)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)
