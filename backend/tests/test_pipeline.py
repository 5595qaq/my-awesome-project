import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock

import asyncpg
import pytest
from pgqueuer import PgQueuer

from app.db import asyncpg_dsn
from app.services import agents, evaluation_queue as repo, gemini_service
from app.worker import register
from app.config import settings

SEGMENTS = {
    "agent_A": {"start": "00:00", "end": "01:00"},
    "agent_B": {"start": "00:40", "end": "02:00"},
    "agent_C": {"start": "01:40", "end": "03:00"},
    "agent_D": {"start": "02:40", "end": "04:00"},
}


@asynccontextmanager
async def workers(pool, count=1):
    connections, queues, tasks = [], [], []
    try:
        for _ in range(count):
            conn = await asyncpg.connect(asyncpg_dsn())
            connections.append(conn)
            queue = PgQueuer.from_asyncpg_connection(conn)
            register(queue, pool)
            queues.append(queue)
            tasks.append(asyncio.create_task(queue.qm.run(
                batch_size=5, max_concurrent_tasks=10, dequeue_timeout=timedelta(milliseconds=20),
            )))
        yield queues
    finally:
        for queue in queues:
            queue.shutdown.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 10)
        for conn in connections:
            await conn.close()


async def wait_terminal(pool, job_ids):
    async def wait():
        while True:
            rows = await pool.fetch("SELECT * FROM evaluation_jobs WHERE id=ANY($1::varchar[])", job_ids)
            if len(rows) == len(job_ids) and all(r["status"] in repo.TERMINAL for r in rows):
                return rows
            await asyncio.sleep(.02)
    return await asyncio.wait_for(wait(), 20)


async def create(pool, count):
    uris = [f"gs://bucket/video-{i}.mp4" for i in range(count)]
    async with pool.acquire() as conn:
        job = await repo.create_evaluation(conn, "exam", uris)
    return job


@pytest.fixture
def fake_models(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_CALL_STAGGER_MS", 0)
    monkeypatch.setattr(gemini_service.gcs_service, "blob_exists_at_uri", lambda uri: True)
    cutting = AsyncMock(return_value=SEGMENTS)
    scoring = AsyncMock(side_effect=lambda uri, agent, topic, segment: [{"Video_Path": uri, "Agent_Name": agent}])
    monkeypatch.setattr(agents, "run_time_cutting_agent", cutting)
    monkeypatch.setattr(agents, "run_agent", scoring)
    return cutting, scoring


async def test_23_videos_window_refills_only_after_four_scores(pool, fake_models):
    job = await create(pool, 23)
    counts = dict(await pool.fetch("SELECT status,count(*) FROM evaluation_videos GROUP BY status"))
    assert counts == {"queued": 10, "pending": 13}
    video = await pool.fetchrow("SELECT * FROM evaluation_videos WHERE job_id=$1 ORDER BY position LIMIT 1", job["id"])
    call = repo.ModelCall(evaluation_id=job["id"], video_id=video["id"], action="segment")
    await repo.persist_result(pool, call, SEGMENTS)
    for name in agents.AGENT_NAMES[:3]:
        await repo.persist_result(pool, call.model_copy(update={"action": "score", "agent": name}), [])
    assert await pool.fetchval("SELECT count(*) FROM evaluation_videos WHERE status='pending'") == 13
    await repo.persist_result(pool, call.model_copy(update={"action": "score", "agent": "Agent_D"}), [])
    assert await pool.fetchval("SELECT count(*) FROM evaluation_videos WHERE status='pending'") == 12
    assert await pool.fetchval("SELECT count(*) FROM evaluation_videos WHERE status IN ('queued','segmenting','scoring')") == 10
    # Existing completed stages in the queue are skipped; the rest completes normally.
    async with workers(pool, 2):
        rows = await wait_terminal(pool, [job["id"]])
    assert rows[0]["status"] == "finished"
    assert await pool.fetchval("SELECT completed_steps FROM evaluation_progress") == 115


async def test_two_workers_share_five_calls_progress_and_order(pool, monkeypatch, fake_models):
    active = peak = 0
    seen = []
    window_counts = []
    progress_events = []
    listener = await asyncpg.connect(asyncpg_dsn())

    def notification(conn, pid, channel, payload):
        data = json.loads(payload)
        if data["branch_name"] == "GEMINI_PROCESSING" and data["progress"]:
            progress_events.append((data["job_id"], int(data["progress"].split('/')[0])))

    await listener.add_listener("branch_updates", notification)

    async def model(uri, agent=None, *args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        seen.append((uri, agent))
        try:
            window_counts.extend(await pool.fetch(
                "SELECT count(*) AS n FROM evaluation_videos WHERE status IN ('queued','segmenting','scoring') GROUP BY job_id"))
            await asyncio.sleep(.03 if agent is None else .01 * (5 - agents.AGENT_NAMES.index(agent)))
            return SEGMENTS if agent is None else [{"Video_Path": uri, "Agent_Name": agent}]
        finally:
            active -= 1

    monkeypatch.setattr(agents, "run_time_cutting_agent", model)
    monkeypatch.setattr(agents, "run_agent", model)
    jobs = [await create(pool, 10), await create(pool, 10)]
    try:
        async with workers(pool, 2):
            rows = await wait_terminal(pool, [j["id"] for j in jobs])
        assert peak == 5
        assert all(r["n"] <= 10 for r in window_counts)
        assert len(seen) == 100
        for row in rows:
            assert row["status"] == "finished", row["result"]
            result = json.loads(row["result"])
            assert [(i["Video_Path"], i["Agent_Name"]) for i in result["items"]] == [
                (uri, name) for uri in json.loads(row["video_paths"]) for name in agents.AGENT_NAMES]
            values = [p for job_id, p in progress_events if job_id == row["id"]]
            assert values == list(range(51))
    finally:
        await listener.close()


async def test_enqueue_and_business_state_are_atomic(pool, monkeypatch):
    original = repo.enqueue
    async def broken(conn, call, position=0):
        await original(conn, call, position)
        raise RuntimeError("enqueue interrupted")
    monkeypatch.setattr(repo, "enqueue", broken)
    with pytest.raises(RuntimeError):
        await create(pool, 10)
    assert await pool.fetchval("SELECT count(*) FROM evaluation_jobs") == 0
    assert await pool.fetchval("SELECT count(*) FROM pgqueuer") == 0


async def test_duplicate_completion_is_idempotent_and_fanout_atomic(pool, fake_models, monkeypatch):
    job = await create(pool, 1)
    row = await pool.fetchrow("SELECT payload FROM pgqueuer")
    call = repo.ModelCall.model_validate_json(row["payload"])
    original = repo.enqueue
    async def broken(conn, call, position=0):
        await original(conn, call, position)
        if position == 2:
            raise RuntimeError("fanout interrupted")
    monkeypatch.setattr(repo, "enqueue", broken)
    with pytest.raises(RuntimeError):
        await repo.persist_result(pool, call, SEGMENTS)
    assert await pool.fetchval("SELECT segments FROM evaluation_videos") is None
    assert await pool.fetchval("SELECT count(*) FROM pgqueuer") == 1
    monkeypatch.setattr(repo, "enqueue", original)
    await asyncio.gather(*(repo.persist_result(pool, call, SEGMENTS) for _ in range(3)))
    assert await pool.fetchval("SELECT completed_steps FROM evaluation_progress") == 1
    assert await pool.fetchval("SELECT count(*) FROM pgqueuer") == 5


async def test_failed_parent_skips_pending_and_discards_inflight_results(pool, fake_models):
    job = await create(pool, 10)
    row = await pool.fetchrow("SELECT payload FROM pgqueuer ORDER BY id LIMIT 1")
    call = repo.ModelCall.model_validate_json(row["payload"])
    await repo.prepare_call(pool, call)
    await repo.fail_job(pool, call, RuntimeError("quota retries exhausted"))
    await repo.persist_result(pool, call, SEGMENTS)
    async with workers(pool):
        await asyncio.sleep(.15)
    fake_models[0].assert_not_awaited()
    assert await pool.fetchval("SELECT completed_steps FROM evaluation_progress") == 0
    assert await pool.fetchval("SELECT status FROM evaluation_jobs") == "failed"


async def test_missing_gcs_video_fails_without_model_call(pool, fake_models, monkeypatch):
    monkeypatch.setattr(gemini_service.gcs_service, "blob_exists_at_uri", lambda uri: False)
    job = await create(pool, 1)
    async with workers(pool):
        rows = await wait_terminal(pool, [job["id"]])
    assert rows[0]["status"] == "failed"
    fake_models[0].assert_not_awaited()


async def test_bootstrap_migrates_unfinished_legacy_once(pool, fake_models):
    await pool.execute("INSERT INTO evaluation_jobs(id,status,video_paths) VALUES('legacy','processing','[\"gs://bucket/a.mp4\"]')")
    async with pool.acquire() as conn:
        await repo.backfill_legacy(conn)
        await repo.backfill_legacy(conn)
    assert await pool.fetchval("SELECT count(*) FROM evaluation_videos") == 1
    assert await pool.fetchval("SELECT count(*) FROM pgqueuer") == 1


async def test_stagger_is_persisted(pool):
    await create(pool, 10)
    delays = await pool.fetch("SELECT execute_after-created AS delay FROM pgqueuer ORDER BY id")
    assert [round(r["delay"].total_seconds(), 2) for r in delays] == [i * .25 for i in range(10)]
