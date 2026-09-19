import asyncio
import hashlib
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File

from app.services import gcs_service, video_service

router = APIRouter()
MAX_PARALLEL_UPLOADS = 2


async def _process_video(safe_filename: str, source_bytes: bytes, source_hash: str,
                         semaphore: asyncio.Semaphore):
    async with semaphore:
        target_filename = f"videos/{source_hash}_5fps.mp4"

        if await asyncio.to_thread(gcs_service.blob_exists, target_filename):
            return {
                "filename": target_filename,
                "gcs_uri": gcs_service.gcs_uri_for(target_filename),
                "status": "skipped_existing",
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / safe_filename
            input_path.write_bytes(source_bytes)

            converted_path = Path(tmp_dir) / f"{source_hash}_5fps.mp4"
            await asyncio.to_thread(
                video_service.convert_to_5fps, str(input_path), str(converted_path),
            )
            with open(converted_path, "rb") as converted_file:
                gcs_uri, status = await asyncio.to_thread(
                    gcs_service.upload_if_needed,
                    converted_file,
                    target_filename,
                    "video/mp4",
                )

        return {"filename": target_filename, "gcs_uri": gcs_uri, "status": status}


@router.post("/")
async def upload_videos(files: List[UploadFile] = File(...)):
    semaphore = asyncio.Semaphore(MAX_PARALLEL_UPLOADS)
    tasks = {}
    ordered = []
    for upload in files:
        source_bytes = await upload.read()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        if source_hash not in tasks:
            tasks[source_hash] = asyncio.create_task(_process_video(
                Path(upload.filename).name, source_bytes, source_hash, semaphore,
            ))
        ordered.append(tasks[source_hash])
    # Reusing the same task deduplicates identical content within one request;
    # gather still preserves the caller's input order.
    return await asyncio.gather(*ordered)
