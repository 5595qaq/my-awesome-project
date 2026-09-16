"""Subprocess worker for crash tests. Only talks to an isolated *_test database."""
import asyncio
import os
from datetime import timedelta
from urllib.parse import urlparse

from app.db import asyncpg_dsn
from app.worker import main
from app.services import agents, gcs_service
from app.services.model_logging import context
from tests.test_pipeline import SEGMENTS


async def run():
    assert urlparse(asyncpg_dsn()).path.endswith("_test")
    async with main() as queue:
        # Own connection for test observations, separate from the queue listener.
        import asyncpg
        async with asyncpg.create_pool(asyncpg_dsn(), min_size=1, max_size=5) as pool:
            async def fake(uri, agent=None, *args):
                stage = "segment" if agent is None else "score"
                row_id = await pool.fetchval(
                    "INSERT INTO queue_test_calls(video_id,stage,agent) VALUES($1,$2,$3) RETURNING id",
                    context.get()["video_id"], stage, agent,
                )
                await asyncio.sleep(60 if os.getenv("VLM_TEST_PAUSE_STAGE") == stage else .04)
                await pool.execute("UPDATE queue_test_calls SET ended=clock_timestamp() WHERE id=$1", row_id)
                return SEGMENTS if agent is None else [{"Video_Path": uri, "Agent_Name": agent}]
            agents.run_time_cutting_agent = fake
            agents.run_agent = fake
            gcs_service.blob_exists_at_uri = lambda uri: True
            await queue.run(dequeue_timeout=timedelta(milliseconds=50), heartbeat_timeout=timedelta(seconds=1),
                            batch_size=5, max_concurrent_tasks=10)


if __name__ == "__main__":
    asyncio.run(run())
