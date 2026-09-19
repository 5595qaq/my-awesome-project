import asyncio
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.services import gcs_service, video_service

router = APIRouter()
MAX_PARALLEL_UPLOADS = 2


async def _process_video(f: UploadFile, semaphore: asyncio.Semaphore):
    async with semaphore:
        safe_filename = Path(f.filename).name
        stem = Path(safe_filename).stem
        suffix = Path(safe_filename).suffix
        base_stem = stem[:-5] if stem.endswith("_1fps") else stem
        target_filename = f"{base_stem}_1fps{suffix}"
        gaze_filename = f"{base_stem}_gaze_5fps{suffix}"

        # Skip both the (expensive) ffmpeg conversion and the upload if this
        # video has already been processed and stored before.
        score_exists, gaze_exists = await asyncio.gather(
            asyncio.to_thread(gcs_service.blob_exists, target_filename),
            asyncio.to_thread(gcs_service.blob_exists, gaze_filename),
        )
        if score_exists and gaze_exists:
            return {
                "filename": target_filename,
                "gcs_uri": gcs_service.gcs_uri_for(target_filename),
                "gaze_filename": gaze_filename,
                "gaze_gcs_uri": gcs_service.gcs_uri_for(gaze_filename),
                "status": "skipped_existing",
            }
        if stem.endswith("_1fps") and not gaze_exists:
            raise HTTPException(
                status_code=422,
                detail=f"{safe_filename} cannot produce a true 5 FPS gaze source; upload the original video",
            )

        # Every parallel task owns its temporary directory, so conversion and
        # cleanup cannot interfere with another video in the same request.
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / safe_filename
            input_path.write_bytes(await f.read())

            converted_path = Path(tmp_dir) / target_filename
            gaze_path = Path(tmp_dir) / gaze_filename
            if not score_exists:
                await asyncio.to_thread(
                    video_service.convert_to_1fps,
                    str(input_path),
                    str(converted_path),
                )
            if not gaze_exists:
                await asyncio.to_thread(
                    video_service.convert_to_5fps, str(input_path), str(gaze_path),
                )
            if score_exists:
                gcs_uri, score_status = gcs_service.gcs_uri_for(target_filename), "skipped_existing"
            else:
                with open(converted_path, "rb") as converted_file:
                    gcs_uri, score_status = await asyncio.to_thread(
                    gcs_service.upload_if_needed,
                    converted_file,
                    target_filename,
                    "video/mp4",
                )
            if gaze_exists:
                gaze_uri, gaze_status = gcs_service.gcs_uri_for(gaze_filename), "skipped_existing"
            else:
                with open(gaze_path, "rb") as gaze_file:
                    gaze_uri, gaze_status = await asyncio.to_thread(
                        gcs_service.upload_if_needed, gaze_file, gaze_filename, "video/mp4",
                    )

        status = "skipped_existing" if score_status == gaze_status == "skipped_existing" else "uploaded"
        return {"filename": target_filename, "gcs_uri": gcs_uri, "gaze_filename": gaze_filename,
                "gaze_gcs_uri": gaze_uri, "status": status}


@router.post("/")
async def upload_videos(files: List[UploadFile] = File(...)):
    semaphore = asyncio.Semaphore(MAX_PARALLEL_UPLOADS)
    # asyncio.gather preserves awaitable order even when later videos finish
    # first, keeping the response aligned with the browser's selected files.
    return await asyncio.gather(*(_process_video(f, semaphore) for f in files))
