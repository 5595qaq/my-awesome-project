"""Explicit, idempotent schema setup before API/worker startup."""
import asyncio

import asyncpg
from pgqueuer.db import AsyncpgDriver
from pgqueuer.queries import Queries

from app.db import asyncpg_dsn, init_db
from app.services.evaluation_queue import backfill_legacy


async def main():
    await asyncio.to_thread(init_db)
    connection = await asyncpg.connect(asyncpg_dsn())
    try:
        await connection.execute(
            "ALTER TABLE evaluation_jobs ADD COLUMN IF NOT EXISTS generation integer NOT NULL DEFAULT 0"
        )
        await connection.execute(
            "ALTER TABLE evaluation_jobs ALTER COLUMN generation SET DEFAULT 0"
        )
        for statement in (
            "ALTER TABLE evaluation_videos ADD COLUMN IF NOT EXISTS gaze_source_uri varchar",
            "ALTER TABLE evaluation_videos ADD COLUMN IF NOT EXISTS gaze_overlay_uri varchar",
            "ALTER TABLE evaluation_videos ADD COLUMN IF NOT EXISTS gaze_metadata_uri varchar",
            "ALTER TABLE evaluation_videos ADD COLUMN IF NOT EXISTS gaze_status varchar NOT NULL DEFAULT 'pending'",
            "ALTER TABLE evaluation_videos ADD COLUMN IF NOT EXISTS gaze_error varchar",
        ):
            await connection.execute(statement)
        queries = Queries(AsyncpgDriver(connection))
        # The same library operations as pgq install / pgq upgrade (durable default).
        if await connection.fetchval("SELECT to_regclass('pgqueuer')"):
            await queries.upgrade()
        else:
            await queries.install()
        await backfill_legacy(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
