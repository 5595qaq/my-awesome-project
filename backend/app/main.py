import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import evaluations
from app.db import engine, Base

# Create tables if they do not exist
Base.metadata.create_all(bind=engine)

app = FastAPI(title="VLM+LLM Nursing Exam API")

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
