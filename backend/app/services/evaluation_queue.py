"""Business transitions are short transactions; PgQueuer owns job delivery.

All transitions lock the parent evaluation before touching children. Model calls
hold no DB lock/connection. Follow-up enqueue and result writes commit together.
"""
import json
import uuid
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from pgqueuer.db import AsyncpgDriver
from pgqueuer.queries import Queries

from app.config import settings
from app.services import agents

ENTRYPOINT = "gemini_api_call"
TERMINAL = {"finished", "failed"}


class ModelCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    evaluation_id: str
    video_id: str
    action: Literal["segment", "score"]
    agent: Literal["Agent_A", "Agent_B", "Agent_C", "Agent_D"] | None = None
    generation: int = 0

    @model_validator(mode="after")
    def validate_agent(self):
        if (self.action == "score") != (self.agent is not None):
            raise ValueError("Only score calls must specify an agent")
        return self


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


async def enqueue(conn, call: ModelCall, position: int = 0):
    base = f"segment:{call.video_id}" if call.action == "segment" else f"score:{call.video_id}:{call.agent}"
    key = f"{base}:{call.generation}"
    await Queries(AsyncpgDriver(conn)).enqueue(
        ENTRYPOINT, call.model_dump_json().encode(),
        execute_after=timedelta(milliseconds=position * settings.GEMINI_CALL_STAGGER_MS), dedupe_key=key,
    )


async def lock_job(conn, job_id):
    return await conn.fetchrow("SELECT * FROM evaluation_jobs WHERE id=$1 FOR UPDATE", job_id)


async def branch(conn, job_id, name, status, message=None, progress=None):
    # Parent lock serializes creation of FINISHED as well as branch updates.
    updated = await conn.execute(
        "UPDATE job_branches SET status=$3, message=$4, progress=COALESCE($5, progress) "
        "WHERE job_id=$1 AND branch_name=$2", job_id, name, status, message, progress,
    )
    if updated == "UPDATE 0":
        await conn.execute(
            "INSERT INTO job_branches(id,job_id,branch_name,status,message,progress) VALUES($1,$2,$3,$4,$5,$6)",
            str(uuid.uuid4()), job_id, name, status, message, progress,
        )


async def fill_window(conn, job_id):
    """Caller holds the parent row lock, including during initial creation."""
    generation = await conn.fetchval("SELECT generation FROM evaluation_jobs WHERE id=$1", job_id)
    active = await conn.fetchval(
        "SELECT count(*) FROM evaluation_videos WHERE job_id=$1 "
        "AND status IN ('queued','segmenting','scoring')", job_id,
    )
    videos = await conn.fetch(
        "SELECT id,segments FROM evaluation_videos WHERE job_id=$1 AND status='pending' ORDER BY position LIMIT $2",
        job_id, max(0, settings.MAX_ACTIVE_VIDEOS_PER_EVALUATION - active),
    )
    for position, video in enumerate(videos):
        if video["segments"] is None:
            await conn.execute("UPDATE evaluation_videos SET status='queued' WHERE id=$1", video["id"])
            await enqueue(conn, ModelCall(evaluation_id=job_id, video_id=video["id"], action="segment",
                                          generation=generation), position)
            continue
        runs = await conn.fetch(
            "SELECT agent_name FROM evaluation_agent_runs WHERE video_id=$1 AND status <> 'finished' "
            "ORDER BY agent_name", video["id"],
        )
        if not runs:
            await conn.execute("UPDATE evaluation_videos SET status='finished' WHERE id=$1", video["id"])
            continue
        await conn.execute("UPDATE evaluation_videos SET status='scoring' WHERE id=$1", video["id"])
        for agent_position, run in enumerate(runs):
            await enqueue(conn, ModelCall(evaluation_id=job_id, video_id=video["id"], action="score",
                                          agent=run["agent_name"], generation=generation),
                          position + agent_position)


async def initialize_videos(conn, job_id, video_paths):
    await conn.execute(
        "INSERT INTO evaluation_progress(job_id,total_steps,completed_steps) VALUES($1,$2,0)",
        job_id, len(video_paths) * 5,
    )
    for position, uri in enumerate(video_paths):
        video_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO evaluation_videos(id,job_id,position,uri,status,verified) VALUES($1,$2,$3,$4,'pending',false)",
            video_id, job_id, position, uri,
        )
        await conn.executemany(
            "INSERT INTO evaluation_agent_runs(id,video_id,agent_name,status) VALUES($1,$2,$3,'pending')",
            [(str(uuid.uuid4()), video_id, name) for name in agents.AGENT_NAMES],
        )
    await fill_window(conn, job_id)


async def create_evaluation(conn, exam_topic, video_paths):
    job_id = str(uuid.uuid4())
    async with conn.transaction():
        await conn.execute(
            "INSERT INTO evaluation_jobs(id,exam_topic,processing_mode,status,generation,video_paths) "
            "VALUES($1,$2,'standard','pending',0,$3::json)", job_id, exam_topic, json.dumps(video_paths),
        )
        for name in ("GEMINI_UPLOAD", "GEMINI_PROCESSING", "LLM_SCORING"):
            await branch(conn, job_id, name, "pending")
        await initialize_videos(conn, job_id, video_paths)
    return dict(id=job_id, exam_topic=exam_topic, status="pending", video_paths=video_paths, result=None)


async def prepare_call(pool, call: ModelCall):
    async with pool.acquire() as conn, conn.transaction():
        job = await lock_job(conn, call.evaluation_id)
        if not job or job["status"] in TERMINAL:
            return None
        if call.generation != job["generation"]:
            return None
        video = await conn.fetchrow(
            "SELECT * FROM evaluation_videos WHERE id=$1 AND job_id=$2", call.video_id, call.evaluation_id,
        )
        if not video:
            raise ValueError("Queue payload references an unknown video")
        if call.action == "segment":
            if video["segments"] is not None:
                return None
            await conn.execute("UPDATE evaluation_videos SET status='segmenting' WHERE id=$1", call.video_id)
            if job["status"] == "pending":
                await conn.execute("UPDATE evaluation_jobs SET status='uploading' WHERE id=$1", call.evaluation_id)
                await branch(conn, call.evaluation_id, "GEMINI_UPLOAD", "in-progress", "Verifying uploaded videos in GCS...")
        else:
            run = await conn.fetchrow(
                "SELECT status FROM evaluation_agent_runs WHERE video_id=$1 AND agent_name=$2", call.video_id, call.agent,
            )
            if run["status"] == "finished":
                return None
            if video["segments"] is None:
                raise ValueError("Scoring cannot start before segmentation")
            await conn.execute(
                "UPDATE evaluation_agent_runs SET status='processing' WHERE video_id=$1 AND agent_name=$2",
                call.video_id, call.agent,
            )
        return {**dict(video), "exam_topic": job["exam_topic"], "segments": decoded(video["segments"])}


async def mark_verified(pool, call):
    async with pool.acquire() as conn, conn.transaction():
        job = await lock_job(conn, call.evaluation_id)
        if not job or job["status"] in TERMINAL or call.generation != job["generation"]:
            return False
        await conn.execute("UPDATE evaluation_videos SET verified=true WHERE id=$1", call.video_id)
        counts = await conn.fetchrow(
            "SELECT count(*) AS total, count(*) FILTER (WHERE verified) AS verified FROM evaluation_videos WHERE job_id=$1",
            call.evaluation_id,
        )
        await branch(conn, call.evaluation_id, "GEMINI_UPLOAD",
                     "completed" if counts["total"] == counts["verified"] else "in-progress",
                     "Verifying uploaded videos in GCS...", f"{counts['verified']}/{counts['total']}")
        if job["status"] != "processing":
            await conn.execute("UPDATE evaluation_jobs SET status='processing' WHERE id=$1", call.evaluation_id)
            total = await conn.fetchval("SELECT total_steps FROM evaluation_progress WHERE job_id=$1", call.evaluation_id)
            await branch(conn, call.evaluation_id, "GEMINI_PROCESSING", "in-progress",
                         "Starting standard mode video analysis...", f"0/{total}")
        return True


async def report_segment_progress(pool, call, phase, elapsed_seconds):
    """Publish a heartbeat without advancing the completed-step counter."""
    async with pool.acquire() as conn, conn.transaction():
        job = await lock_job(conn, call.evaluation_id)
        if not job or job["status"] in TERMINAL or call.generation != job["generation"]:
            return False
        video = await conn.fetchrow(
            "SELECT uri FROM evaluation_videos WHERE id=$1 AND job_id=$2",
            call.video_id, call.evaluation_id,
        )
        if not video:
            return False
        progress = await conn.fetchrow(
            "SELECT completed_steps,total_steps FROM evaluation_progress WHERE job_id=$1",
            call.evaluation_id,
        )
        await branch(
            conn, call.evaluation_id, "GEMINI_PROCESSING", "in-progress",
            f"Time_cuting {phase} | {elapsed_seconds}s | {video['uri']}",
            f"{progress['completed_steps']}/{progress['total_steps']}",
        )
        return True


async def persist_result(pool, call, result):
    async with pool.acquire() as conn, conn.transaction():
        job = await lock_job(conn, call.evaluation_id)
        if not job or job["status"] in TERMINAL or call.generation != job["generation"]:
            return
        video = await conn.fetchrow("SELECT * FROM evaluation_videos WHERE id=$1", call.video_id)
        if call.action == "segment":
            if video["segments"] is not None:
                return
            await conn.execute("UPDATE evaluation_videos SET segments=$2::json,status='scoring' WHERE id=$1",
                               call.video_id, json.dumps(result))
            for position, name in enumerate(agents.AGENT_NAMES):
                await enqueue(conn, ModelCall(evaluation_id=call.evaluation_id, video_id=call.video_id,
                                              action="score", agent=name,
                                              generation=call.generation), position)
            message = f"Time_cuting finished segmenting {video['uri']}"
        else:
            updated = await conn.execute(
                "UPDATE evaluation_agent_runs SET status='finished',result=$3::json "
                "WHERE video_id=$1 AND agent_name=$2 AND status <> 'finished'",
                call.video_id, call.agent, json.dumps(result),
            )
            if updated == "UPDATE 0":
                return
            message = f"{call.agent} finished analyzing {video['uri']}"
            remaining = await conn.fetchval(
                "SELECT count(*) FROM evaluation_agent_runs WHERE video_id=$1 AND status <> 'finished'", call.video_id,
            )
            if remaining == 0:
                await conn.execute("UPDATE evaluation_videos SET status='finished' WHERE id=$1", call.video_id)
                await fill_window(conn, call.evaluation_id)
        progress = await conn.fetchrow(
            "UPDATE evaluation_progress SET completed_steps=completed_steps+1 WHERE job_id=$1 RETURNING *",
            call.evaluation_id,
        )
        complete = progress["completed_steps"] == progress["total_steps"]
        await branch(conn, call.evaluation_id, "GEMINI_PROCESSING", "completed" if complete else "in-progress",
                     message, f"{progress['completed_steps']}/{progress['total_steps']}")
        if complete:
            await finalize(conn, call.evaluation_id)


async def finalize(conn, job_id):
    await branch(conn, job_id, "LLM_SCORING", "in-progress", "Aggregating agent outputs...")
    videos = await conn.fetch("SELECT * FROM evaluation_videos WHERE job_id=$1 ORDER BY position", job_id)
    runs = await conn.fetch(
        "SELECT r.* FROM evaluation_agent_runs r JOIN evaluation_videos v ON v.id=r.video_id "
        "WHERE v.job_id=$1 ORDER BY v.position,r.agent_name", job_id,
    )
    result = {"segments": {v["uri"]: decoded(v["segments"]) for v in videos},
              "items": [item for r in runs for item in decoded(r["result"])]}
    await conn.execute("UPDATE evaluation_jobs SET status='finished',result=$2::json WHERE id=$1", job_id, json.dumps(result))
    await branch(conn, job_id, "LLM_SCORING", "completed", "Evaluation completed successfully.")
    await branch(conn, job_id, "FINISHED", "completed", "done")


async def fail_job(pool, call, exc):
    async with pool.acquire() as conn, conn.transaction():
        job = await lock_job(conn, call.evaluation_id)
        if not job or job["status"] in TERMINAL or call.generation != job["generation"]:
            return
        message = str(exc)
        await conn.execute("UPDATE evaluation_jobs SET status='failed',result=$2::json WHERE id=$1",
                           call.evaluation_id, json.dumps({"error": message}))
        await conn.execute("UPDATE evaluation_videos SET status='failed',error=$2 WHERE job_id=$1 AND status <> 'finished'",
                           call.evaluation_id, message)
        await conn.execute(
            "UPDATE evaluation_agent_runs SET status='failed' WHERE status <> 'finished' AND video_id IN "
            "(SELECT id FROM evaluation_videos WHERE job_id=$1)", call.evaluation_id,
        )
        await branch(conn, call.evaluation_id, "GEMINI_PROCESSING", "failed",
                     f"Execution failed: {message}")


async def retry_evaluation(pool, job_id):
    """Resume only unfinished work in a failed evaluation."""
    async with pool.acquire() as conn, conn.transaction():
        job = await lock_job(conn, job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] != "failed":
            raise ValueError("Only failed evaluations can be retried")

        await conn.execute(
            "UPDATE evaluation_jobs SET status='processing',result=NULL,generation=generation+1 WHERE id=$1", job_id,
        )
        await conn.execute(
            "UPDATE evaluation_videos SET status='pending',error=NULL "
            "WHERE job_id=$1 AND status <> 'finished'", job_id,
        )
        await conn.execute(
            "UPDATE evaluation_agent_runs SET status='pending' WHERE status <> 'finished' AND video_id IN "
            "(SELECT id FROM evaluation_videos WHERE job_id=$1)", job_id,
        )
        progress = await conn.fetchrow(
            "SELECT completed_steps,total_steps FROM evaluation_progress WHERE job_id=$1", job_id,
        )
        await branch(conn, job_id, "GEMINI_PROCESSING", "in-progress",
                     "Resuming unfinished video analysis...",
                     f"{progress['completed_steps']}/{progress['total_steps']}")
        await branch(conn, job_id, "LLM_SCORING", "pending", None)
        await fill_window(conn, job_id)
        return dict(id=job["id"], exam_topic=job["exam_topic"], status="processing",
                    video_paths=decoded(job["video_paths"]), result=None)


async def backfill_legacy(conn):
    """One-time bootstrap; stop old workers before running this migration."""
    async with conn.transaction():
        jobs = await conn.fetch(
            "SELECT * FROM evaluation_jobs j WHERE status NOT IN ('finished','failed') "
            "AND NOT EXISTS (SELECT 1 FROM evaluation_progress p WHERE p.job_id=j.id) FOR UPDATE",
        )
        for job in jobs:
            paths = decoded(job["video_paths"])
            if not paths:
                await conn.execute("UPDATE evaluation_jobs SET status='failed',result=$2::json WHERE id=$1",
                                   job["id"], json.dumps({"error": "Legacy job has no videos"}))
                await conn.execute("UPDATE job_branches SET status='failed',message='Legacy job has no videos' WHERE job_id=$1", job["id"])
                continue
            await conn.execute("UPDATE evaluation_jobs SET status='pending' WHERE id=$1", job["id"])
            for name in ("GEMINI_UPLOAD", "GEMINI_PROCESSING", "LLM_SCORING"):
                await branch(conn, job["id"], name, "pending", "Migrated to PostgreSQL queue", "0/0")
            await initialize_videos(conn, job["id"], paths)
