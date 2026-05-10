<<<<<<< HEAD
from fastapi import APIRouter, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
=======
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
>>>>>>> 24ce401df09b9b7480682717687a446ee98805c5
from sqlalchemy.orm import Session
import os
import uuid
import traceback

from app.db import get_db
<<<<<<< HEAD
from app.schemas.evaluation import EvaluationResponse
from app.models.evaluation import EvaluationJob
from app.services.gemini_service import process_evaluation_job, job_api_keys
=======
from app.schemas.evaluation import EvaluationCreate, EvaluationResponse
from app.models.evaluation import EvaluationJob, JobBranch
from app.services.gemini_service import job_api_keys
>>>>>>> 24ce401df09b9b7480682717687a446ee98805c5
from app.ws_manager import manager

router = APIRouter()

@router.post("/", response_model=EvaluationResponse)
<<<<<<< HEAD
async def create_evaluation(
    background_tasks: BackgroundTasks,
    student_id: str = Form(...),
    exam_topic: str = Form(...),
    gemini_api_key: str = Form(...),
    videos: list[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    try:
        temp_dir = "/app/temp_videos"
        os.makedirs(temp_dir, exist_ok=True)
        saved_video_paths = []

        for video in videos:
            unique_filename = f"{uuid.uuid4()}_{video.filename}"
            file_location = os.path.join(temp_dir, unique_filename)
            with open(file_location, "wb+") as file_object:
                file_object.write(await video.read()) 
            saved_video_paths.append(file_location)

        job = EvaluationJob(
            student_id=student_id,
            exam_topic=exam_topic,
            video_paths=saved_video_paths, 
            status="pending",
            processing_mode="standard"
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        job_api_keys[job.id] = gemini_api_key
        # 把任務丟進背景執行
        background_tasks.add_task(process_evaluation_job, job.id, db)
        
        return job

    except Exception as e:
        print(f"❌ 建立任務失敗: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"伺服器錯誤: {str(e)}")

=======
def create_evaluation(
    eval_in: EvaluationCreate,
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
>>>>>>> 24ce401df09b9b7480682717687a446ee98805c5

@router.websocket("/{job_id}/ws")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    print(f"🔗 收到 WebSocket 連線請求: Job ID = {job_id}")
    
    # 這裡會呼叫 ws_manager 的 accept()
    await manager.connect(websocket, job_id)
<<<<<<< HEAD
    print(f"✅ WebSocket 連線已成功接聽: {job_id}")
    
=======
    print("WebSocket 成功連線！", flush=True)
>>>>>>> 24ce401df09b9b7480682717687a446ee98805c5
    try:
        while True:
            # 保持連線開啟，等待前端中斷或後端完成
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)
        print(f"❌ WebSocket 已中斷: {job_id}")