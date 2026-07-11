from fastapi import APIRouter, UploadFile, File
from typing import List

from app.services import gcs_service

router = APIRouter()


@router.post("/")
async def upload_videos(files: List[UploadFile] = File(...)):
    results = []
    for f in files:
        gcs_uri, status = gcs_service.upload_if_needed(f.file, f.filename, content_type=f.content_type)
        results.append({"filename": f.filename, "gcs_uri": gcs_uri, "status": status})
    return results
