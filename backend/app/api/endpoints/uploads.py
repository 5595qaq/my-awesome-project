import asyncio
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File

from app.services import gcs_service, video_service

router = APIRouter()


@router.post("/")
async def upload_videos(files: List[UploadFile] = File(...)):
    results = []

    for f in files:
        safe_filename = Path(f.filename).name
        stem = Path(safe_filename).stem
        suffix = Path(safe_filename).suffix
        already_1fps = stem.endswith("_1fps")
        target_filename = safe_filename if already_1fps else f"{stem}_1fps{suffix}"

        # Skip both the (expensive) ffmpeg conversion and the upload if this
        # video has already been processed and stored before.
        if await asyncio.to_thread(gcs_service.blob_exists, target_filename):
            results.append({
                "filename": target_filename,
                "gcs_uri": gcs_service.gcs_uri_for(target_filename),
                "status": "skipped_existing",
            })
            continue

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / safe_filename
            input_path.write_bytes(await f.read())

            if already_1fps:
                converted_path = input_path
            else:
                converted_path = Path(tmp_dir) / target_filename
                await asyncio.to_thread(video_service.convert_to_1fps, str(input_path), str(converted_path))

            with open(converted_path, "rb") as converted_file:
                gcs_uri, status = gcs_service.upload_if_needed(converted_file, target_filename, content_type="video/mp4")

        results.append({"filename": target_filename, "gcs_uri": gcs_uri, "status": status})

    return results
