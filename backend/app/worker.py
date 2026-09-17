"""Run with: pgq run app.worker:main"""
import logging
from contextlib import asynccontextmanager

import asyncpg
from pgqueuer import PgQueuer

from app.config import settings
from app.db import asyncpg_dsn
from app.services import agents
from app.services.evaluation_queue import ENTRYPOINT
from app.services.gemini_service import process_model_call


def register(pgq, pool):
    @pgq.entrypoint(ENTRYPOINT, concurrency_limit=settings.GEMINI_GLOBAL_CONCURRENCY, on_failure="hold")
    async def handle(job):
        await process_model_call(job, pool)


@asynccontextmanager
async def main():
    logging.basicConfig(level=logging.INFO)
    async with asyncpg.create_pool(asyncpg_dsn(), min_size=1, max_size=10) as pool:
        connection = await asyncpg.connect(asyncpg_dsn())
        try:
            pgq = PgQueuer.from_asyncpg_connection(connection)
            register(pgq, pool)
            yield pgq
        finally:
            await agents.close_client()
            await connection.close()
