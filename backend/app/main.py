import asyncio
import json

import asyncpg
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.endpoints import evaluations, uploads
from app.db import DATABASE_URL, SessionLocal, init_db
from app.models.evaluation import EvaluationJob
from app.services.gemini_service import process_evaluation_job
from app.ws_manager import manager


# Create tables and PostgreSQL notification triggers.
init_db()

RECOVERY_INTERVAL_SECONDS = 30
dispatched_jobs: set[str] = set()
worker_tasks: set[asyncio.Task] = set()


def _asyncpg_dsn() -> str:
    if DATABASE_URL.startswith("postgresql+psycopg2://"):
        return DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1)
    return DATABASE_URL


async def _run_claimed_job(job_id: str) -> None:
    lock_connection = None
    lock_acquired = False
    try:
        lock_connection = await asyncpg.connect(_asyncpg_dsn())
        lock_acquired = await lock_connection.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1, 0))",
            job_id,
        )
        if not lock_acquired:
            return

        db = SessionLocal()
        try:
            job = db.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
            if job is None or job.status in {"finished", "failed"}:
                return
            await process_evaluation_job(job_id, db)
        finally:
            db.close()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"Worker error for job {job_id}: {exc}", flush=True)
    finally:
        if lock_connection is not None:
            if lock_acquired:
                try:
                    await lock_connection.execute(
                        "SELECT pg_advisory_unlock(hashtextextended($1, 0))",
                        job_id,
                    )
                except Exception as exc:
                    print(f"Failed to unlock job {job_id}: {exc}", flush=True)
            try:
                await lock_connection.close()
            except Exception as exc:
                print(f"Failed to close lock connection for job {job_id}: {exc}", flush=True)
        dispatched_jobs.discard(job_id)


def dispatch_job(job_id: str) -> bool:
    """Schedule a local contender; the PostgreSQL advisory lock picks one worker."""
    if not job_id or job_id in dispatched_jobs:
        return False
    dispatched_jobs.add(job_id)
    task = asyncio.create_task(_run_claimed_job(job_id))
    worker_tasks.add(task)
    task.add_done_callback(worker_tasks.discard)
    return True


def _handle_notification(connection, pid, channel, payload) -> None:
    try:
        data = json.loads(payload)
        job_id = data.get("job_id")
        branch_name = data.get("branch_name")
        status = data.get("status")
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"Ignoring invalid PostgreSQL notification: {exc}", flush=True)
        return

    event_payload = {
        "stage": branch_name,
        "status": status,
        "progress": data.get("progress"),
        "message": data.get("message"),
    }
    asyncio.create_task(
        manager.broadcast_to_job("BRANCH_STATUS_UPDATE", event_payload, job_id)
    )

    if branch_name == "GEMINI_UPLOAD" and status == "pending":
        if dispatch_job(job_id):
            print(f"PostgreSQL 觸發：偵測到新任務準備啟動 {job_id}", flush=True)


async def pg_listener() -> None:
    """Listen forever, reconnecting with bounded exponential backoff."""
    retry_delay = 1
    while True:
        connection = None
        try:
            connection = await asyncpg.connect(_asyncpg_dsn())
            await connection.add_listener("branch_updates", _handle_notification)
            retry_delay = 1
            await asyncio.Future()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                f"PostgreSQL listener error; retrying in {retry_delay}s: {exc}",
                flush=True,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)
        finally:
            if connection is not None:
                try:
                    await connection.remove_listener("branch_updates", _handle_notification)
                except Exception:
                    pass
                await connection.close()


async def recover_unfinished_jobs_once() -> list[str]:
    """Redispatch jobs whose notification was missed or whose worker stopped."""
    connection = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await connection.fetch(
            """
            SELECT evaluation_jobs.id
            FROM evaluation_jobs
            WHERE evaluation_jobs.status NOT IN ('finished', 'failed')
              AND EXISTS (
                SELECT 1 FROM job_branches
                WHERE job_branches.job_id = evaluation_jobs.id
                  AND job_branches.branch_name = 'GEMINI_UPLOAD'
              )
            """
        )
    finally:
        await connection.close()

    recovered = []
    for row in rows:
        job_id = row["id"]
        if dispatch_job(job_id):
            recovered.append(job_id)
    return recovered


async def recovery_loop() -> None:
    while True:
        try:
            recovered = await recover_unfinished_jobs_once()
            if recovered:
                print(f"Recovery queued {len(recovered)} unfinished job(s)", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"PostgreSQL recovery scan failed: {exc}", flush=True)
        await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    listener_task = asyncio.create_task(pg_listener())
    recovery_task = asyncio.create_task(recovery_loop())
    try:
        yield
    finally:
        listener_task.cancel()
        recovery_task.cancel()
        for task in list(worker_tasks):
            task.cancel()
        await asyncio.gather(
            listener_task,
            recovery_task,
            *list(worker_tasks),
            return_exceptions=True,
        )


app = FastAPI(title="VLM+LLM Nursing Exam API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(evaluations.router, prefix="/api/v1/evaluations", tags=["evaluations"])
app.include_router(uploads.router, prefix="/api/v1/uploads", tags=["uploads"])

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
