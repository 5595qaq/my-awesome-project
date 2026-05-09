from fastapi import APIRouter, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
import os
import uuid
import traceback # 新增這個，用來在終端機印出完整追蹤紀錄

from app.db import get_db
from app.schemas.evaluation import EvaluationResponse
from app.models.evaluation import EvaluationJob
from app.services.gemini_service import process_evaluation_job, job_api_keys
from app.ws_manager import manager

router = APIRouter()

@router.post("/", response_model=EvaluationResponse)
async def create_evaluation(
    background_tasks: BackgroundTasks,
    student_id: str = Form(...),
    exam_topic: str = Form(...),
    gemini_api_key: str = Form(...),
    videos: list[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    try: # 👉 新增 try 區塊
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
        background_tasks.add_task(process_evaluation_job, job.id, db)
        
        return job

    except Exception as e: # 👉 如果上面發生任何錯誤，就會跳到這裡
        # 在 Docker 終端機印出紅字，方便你 Debug
        print(f"❌ 建立任務失敗: {e}")
        traceback.print_exc()
        
        # 把具體的錯誤訊息 (str(e)) 打包成 HTTP 500 錯誤傳給前端
        raise HTTPException(status_code=500, detail=f"伺服器錯誤: {str(e)}")

# ... 下方的 WebSocket 保持不變 ...