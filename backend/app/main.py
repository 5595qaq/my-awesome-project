import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import evaluations
from app.db import engine, Base

# 建立資料庫資料表
Base.metadata.create_all(bind=engine)

app = FastAPI(title="VLM+LLM Nursing Exam API")

# 針對 HTTP 與 WebSocket 的 CORS 放行設定
origins = [
    "*",
    "http://localhost:8080",
    "http://127.0.0.1:5641",
    "http://127.0.0.1:5500",
    "http://localhost:5500"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(evaluations.router, prefix="/api/v1/evaluations", tags=["evaluations"])

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)