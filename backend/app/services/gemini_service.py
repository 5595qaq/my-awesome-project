import asyncio
import logging
import time

from sqlalchemy.orm import Session

from app.models.evaluation import EvaluationJob, JobBranch
from app.services import agents, gcs_service


# Use the configured server logger so phase timings appear in container logs.
logger = logging.getLogger("uvicorn.error.analysis_progress")
SEGMENT_PROGRESS_INTERVAL_SECONDS = 15

def _update_branch(db: Session, job_id: str, branch_name: str, **values) -> None:
    db.query(JobBranch).filter_by(job_id=job_id, branch_name=branch_name).update(values)
    db.commit()


async def _segment_with_progress(db, job_id, video_uri, progress):
    """Report real phase changes and elapsed time without inventing completion %."""
    started = phase_started = time.monotonic()
    phase = "queued"

    def publish():
        elapsed = int(time.monotonic() - started)
        _update_branch(
            db, job_id, "GEMINI_PROCESSING",
            progress=progress,
            message=f"Time_cuting {phase} | {elapsed}s | {video_uri}",
        )

    def report(next_phase):
        nonlocal phase, phase_started
        now = time.monotonic()
        logger.info(
            "Segmentation job=%s video=%s phase=%s phase_seconds=%.1f next=%s",
            job_id, video_uri, phase, now - phase_started, next_phase,
        )
        phase, phase_started = next_phase, now
        publish()

    publish()
    task = asyncio.create_task(agents.run_time_cutting_agent(video_uri, on_progress=report))
    outcome = "failed"
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=SEGMENT_PROGRESS_INTERVAL_SECONDS)
            if done:
                result = task.result()
                outcome = "completed"
                return result
            publish()
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        logger.info(
            "Segmentation job=%s video=%s phase=%s phase_seconds=%.1f total_seconds=%.1f outcome=%s",
            job_id, video_uri, phase, time.monotonic() - phase_started,
            time.monotonic() - started, outcome,
        )


async def _run_named_agent(
    video_uri: str,
    agent_name: str,
    exam_topic: str,
    segment: dict[str, str],
) -> tuple[str, list[dict]]:
    items = await agents.run_agent(video_uri, agent_name, exam_topic, segment)
    return agent_name, items


async def process_evaluation_job(job_id: str, db: Session):
    print(f"開始執行背景任務 process_evaluation_job: {job_id}", flush=True)

    job = db.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
    if not job:
        print(f"Error: Job {job_id} not found in DB")
        return

    try:
        # Phase 1: confirm that every submitted gs:// object exists.
        job.status = "uploading"
        total_steps = len(job.video_paths) * (1 + len(agents.AGENT_NAMES))
        _update_branch(
            db,
            job_id,
            "GEMINI_UPLOAD",
            status="in-progress",
            message="Verifying uploaded videos in GCS...",
        )

        for index, video_uri in enumerate(job.video_paths):
            exists = await asyncio.to_thread(gcs_service.blob_exists_at_uri, video_uri)
            if not exists:
                raise FileNotFoundError(f"Video not found in GCS: {video_uri}")

            _update_branch(
                db,
                job_id,
                "GEMINI_UPLOAD",
                progress=f"{index + 1}/{len(job.video_paths)}",
                message=f"Confirmed {video_uri}",
            )

        _update_branch(db, job_id, "GEMINI_UPLOAD", status="completed")

        # Phase 2: time-cut each video, then run its four scoring agents in parallel.
        job.status = "processing"
        _update_branch(
            db,
            job_id,
            "GEMINI_PROCESSING",
            status="in-progress",
            progress=f"0/{total_steps}",
            message=f"Starting {job.processing_mode} mode video analysis...",
        )

        all_items: list[dict] = []
        segments_by_video: dict[str, dict[str, dict[str, str]]] = {}
        completed_steps = 0

        for video_uri in job.video_paths:
            segments = await _segment_with_progress(
                db, job_id, video_uri, f"{completed_steps}/{total_steps}"
            )
            segments_by_video[video_uri] = segments
            completed_steps += 1
            _update_branch(
                db,
                job_id,
                "GEMINI_PROCESSING",
                progress=f"{completed_steps}/{total_steps}",
                message=f"Time_cuting finished segmenting {video_uri}",
            )

            tasks = [
                asyncio.create_task(
                    _run_named_agent(
                        video_uri,
                        agent_name,
                        job.exam_topic,
                        segments[agents.AGENT_SEGMENT_KEYS[agent_name]],
                    )
                )
                for agent_name in agents.AGENT_NAMES
            ]
            items_by_agent: dict[str, list[dict]] = {}
            try:
                for completed_task in asyncio.as_completed(tasks):
                    agent_name, items = await completed_task
                    items_by_agent[agent_name] = items
                    completed_steps += 1
                    _update_branch(
                        db,
                        job_id,
                        "GEMINI_PROCESSING",
                        progress=f"{completed_steps}/{total_steps}",
                        message=f"{agent_name} finished analyzing {video_uri}",
                    )
            except BaseException:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

            # Completion order is nondeterministic; persisted output order is not.
            for agent_name in agents.AGENT_NAMES:
                all_items.extend(items_by_agent[agent_name])

        _update_branch(db, job_id, "GEMINI_PROCESSING", status="completed")

        # Phase 3: store raw scoring results plus time-cutting diagnostics.
        job.status = "scoring"
        _update_branch(
            db,
            job_id,
            "LLM_SCORING",
            status="in-progress",
            message="Aggregating agent outputs...",
        )

        job.result = {"segments": segments_by_video, "items": all_items}
        job.status = "finished"
        _update_branch(
            db,
            job_id,
            "LLM_SCORING",
            status="completed",
            message="Evaluation completed successfully.",
        )

        finished = db.query(JobBranch).filter_by(job_id=job_id, branch_name="FINISHED").first()
        if finished:
            finished.status = "completed"
            finished.message = "done"
        else:
            db.add(JobBranch(job_id=job_id, branch_name="FINISHED", status="completed", message="done"))
        db.commit()

    except asyncio.CancelledError:
        # Leave the current non-terminal state recoverable after worker shutdown.
        raise
    except Exception as exc:
        if not db.is_active:
            db.rollback()
        job.status = "failed"
        job.result = {"error": str(exc)}
        db.query(JobBranch).filter_by(job_id=job_id).update(
            {"status": "failed", "message": f"Execution failed: {exc}"}
        )
        db.commit()
