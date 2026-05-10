import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

from app.main import app
from app.db import Base, get_db

# Force a test database so we don't wipe the dev DB during tests
base_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/vlm_eval")
if "/vlm_eval_test" not in base_url and "vlm_eval" in base_url:
    SQLALCHEMY_DATABASE_URL = base_url.replace("vlm_eval", "vlm_eval_test")
else:
    # default fallback
    SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    import urllib.parse
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    parsed_orig = urllib.parse.urlparse(base_url)
    test_db_name = urllib.parse.urlparse(SQLALCHEMY_DATABASE_URL).path[1:]

    try:
        conn = psycopg2.connect(
            dbname=parsed_orig.path[1:],
            user=parsed_orig.username,
            password=parsed_orig.password,
            host=parsed_orig.hostname,
            port=parsed_orig.port or 5432
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        cursor.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{test_db_name}'")
        exists = cursor.fetchone()
        if not exists:
            cursor.execute(f"CREATE DATABASE {test_db_name}")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Warning: Could not verify/create database: {e}")

    engine = create_engine(SQLALCHEMY_DATABASE_URL)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session")
def db_engine():
    # Create the database tables
    Base.metadata.create_all(bind=engine)
    yield engine
    # Drop the tables after tests finish
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
            
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
