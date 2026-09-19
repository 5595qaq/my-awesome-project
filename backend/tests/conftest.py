"""DB fixtures only touch an explicitly selected PostgreSQL database ending _test."""
import asyncio
from urllib.parse import urlparse

import asyncpg
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def db_engine():
    from app.db import DATABASE_URL, engine
    if not urlparse(DATABASE_URL).path.endswith("_test"):
        pytest.fail("Set DATABASE_URL to an isolated PostgreSQL database ending in _test")
    from app.bootstrap import main
    asyncio.run(main())
    yield engine
    engine.dispose()


@pytest.fixture
def clean_db(db_engine):
    from sqlalchemy import text
    # Queue metadata references managers; only the queue rows need clearing.
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE evaluation_jobs CASCADE"))
        conn.execute(text("TRUNCATE pgqueuer CASCADE"))
    yield


@pytest.fixture
def db_session(clean_db):
    from app.db import SessionLocal
    with SessionLocal() as session:
        yield session


@pytest.fixture
async def pool(clean_db):
    from app.db import asyncpg_dsn
    async with asyncpg.create_pool(asyncpg_dsn(), min_size=1, max_size=15) as value:
        yield value


@pytest.fixture
def client(db_session, monkeypatch):
    from app.main import app
    monkeypatch.setattr(
        "app.services.gcs_service.blob_exists_at_uri", lambda _uri: True,
    )
    with TestClient(app) as value:
        yield value
