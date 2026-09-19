"""Explicit, idempotent schema setup before API/worker startup."""
import asyncio
import json

import asyncpg
from pgqueuer.db import AsyncpgDriver
from pgqueuer.queries import Queries

from app.db import asyncpg_dsn, init_db

UNIFIED_SOURCE_MIGRATION_ERROR = (
    "Evaluation stopped during the unified 5 FPS video-source upgrade; submit it again."
)


async def migrate_unified_video_source(connection):
    """Retire unfinished dual-source jobs, then remove their source column once."""
    column_exists = await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name='evaluation_videos' AND column_name='gaze_source_uri')"
    )
    if not column_exists:
        return False

    async with connection.transaction():
        stopped = await connection.fetch(
            "UPDATE evaluation_jobs SET status='retired',result=$1::json "
            "WHERE status NOT IN ('finished','failed') RETURNING id",
            json.dumps({"error": UNIFIED_SOURCE_MIGRATION_ERROR}),
        )
        stopped_ids = [row["id"] for row in stopped]
        if stopped_ids:
            await connection.execute(
                "UPDATE evaluation_videos SET status='failed',error=$1,"
                "gaze_status=CASE WHEN gaze_status='finished' THEN gaze_status ELSE 'failed' END,"
                "gaze_error=CASE WHEN gaze_status='finished' THEN gaze_error ELSE $1 END "
                "WHERE job_id=ANY($2::varchar[])",
                UNIFIED_SOURCE_MIGRATION_ERROR, stopped_ids,
            )
            await connection.execute(
                "UPDATE evaluation_agent_runs SET status='failed' WHERE status <> 'finished' AND video_id IN "
                "(SELECT id FROM evaluation_videos WHERE job_id=ANY($1::varchar[]))",
                stopped_ids,
            )
            await connection.execute(
                "UPDATE job_branches SET status='failed',message=$1 "
                "WHERE status <> 'completed' AND job_id=ANY($2::varchar[])",
                UNIFIED_SOURCE_MIGRATION_ERROR, stopped_ids,
            )
        await connection.execute("DELETE FROM pgqueuer")
        await connection.execute("ALTER TABLE evaluation_videos DROP COLUMN gaze_source_uri")
    return True


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
        await migrate_unified_video_source(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
