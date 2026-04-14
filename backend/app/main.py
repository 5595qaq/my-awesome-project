import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import asyncpg
import json
import os

from app.api.endpoints import evaluations
from app.db import engine, Base, init_db, DATABASE_URL, SessionLocal
from app.ws_manager import manager
from app.services.gemini_service import process_evaluation_job

# Create tables and Pub/Sub Triggers
init_db()

# A set to keep track of tasks to avoid duplicate dispatching
dispatched_jobs = set()

async def pg_listener():
    # Helper to adapt sync DSN to asyncpg
    # Sometimes SQLAlchemy url includes 'postgresql+psycopg2://'
    # we convert it natively to standard pg URL
    dsn = DATABASE_URL
    if dsn.startswith("postgresql+psycopg2://"):
        dsn = dsn.replace("postgresql+psycopg2://", "postgresql://")
        
    try:
        conn = await asyncpg.connect(dsn)
        
        def on_notification(connection, pid, channel, payload):
            # Parse trigger JSON payload from Database
            data = json.loads(payload)
            job_id = data.get("job_id")
            branch_name = data.get("branch_name")
            status = data.get("status")
            
            # Map DB schema dict to expected WebSocket payload shape -> {"stage", "progress", ... }
            event_payload = {
                "stage": branch_name,
                "status": status, 
                "progress": data.get("progress"),
                "message": data.get("message")
            }
            
            # Use ws_manager to push changes directly to users asynchronously
            asyncio.create_task(manager.broadcast_to_job("BRANCH_STATUS_UPDATE", event_payload, job_id))

            # --- NEW WORKER LOGIC ---
            # If we detect a new job branch is ready to be handled, we dispatch the worker.
            # We use GEMINI_UPLOAD and pending status to ensure it's a completely new job.
            if branch_name == "GEMINI_UPLOAD" and status == "pending" and job_id not in dispatched_jobs:
                dispatched_jobs.add(job_id)
                print(f"PostgreSQL 觸發：偵測到新任務準備啟動 {job_id}", flush=True)
                
                async def run_task_async(jid: str):
                    db = SessionLocal()
                    try:
                        await process_evaluation_job(jid, db)
                    finally:
                        db.close()
                
                asyncio.create_task(run_task_async(job_id))

        await conn.add_listener('branch_updates', on_notification)
        
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        print(f"PostgreSQL Listener error: {e}", flush=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start pg listener on startup
    listener_task = asyncio.create_task(pg_listener())
    yield
    # Clean up listener on shutdown
    listener_task.cancel()

app = FastAPI(title="VLM+LLM Nursing Exam API", lifespan=lifespan)

# Setup CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(evaluations.router, prefix="/api/v1/evaluations", tags=["evaluations"])

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
