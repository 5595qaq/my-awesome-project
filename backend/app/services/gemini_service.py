"""One queue task runs one logical model stage, never an entire batch."""
import asyncio
import time
from datetime import timedelta

import asyncpg
from pgqueuer import RetryRequested

from app.services import agents, evaluation_queue as repository, gcs_service
from app.services.model_logging import context, emit


async def process_model_call(job, pool):
    call = repository.ModelCall.model_validate_json(job.payload)
    token = context.set({"queue_job_id": job.id, "evaluation_id": call.evaluation_id,
                         "video_id": call.video_id, "agent": call.agent or "Time_cuting",
                         "queue_attempt": job.attempts})
    started = time.monotonic()
    try:
        video = await repository.prepare_call(pool, call)
        if video is None:
            emit("model_stage_skipped")
            return
        if call.action == "segment":
            if not video["verified"]:
                if not await asyncio.to_thread(gcs_service.blob_exists_at_uri, video["uri"]):
                    raise FileNotFoundError(f"Video not found in GCS: {video['uri']}")
            if not await repository.mark_verified(pool, call):
                return
            result = await agents.run_time_cutting_agent(video["uri"])
        else:
            result = await agents.run_agent(video["uri"], call.agent, video["exam_topic"],
                                           video["segments"][agents.AGENT_SEGMENT_KEYS[call.agent]])
        await repository.persist_result(pool, call, result)
        emit("model_stage_completed", elapsed_seconds=round(time.monotonic() - started, 3))
    except asyncio.CancelledError:
        raise  # Worker shutdown must remain recoverable.
    except (asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError, ConnectionError) as exc:
        raise RetryRequested(delay=timedelta(seconds=30), reason=type(exc).__name__) from exc
    except Exception as exc:
        emit("model_stage_failed", error=type(exc).__name__, status_code=getattr(exc, "code", None))
        try:
            await repository.fail_job(pool, call, exc)
        except (asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError, OSError) as db_exc:
            raise RetryRequested(delay=timedelta(seconds=30), reason="Persist failure after model error") from db_exc
        raise
    finally:
        context.reset(token)
