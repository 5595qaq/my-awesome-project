# 測試指南 (TESTING.md)

本文件概述如何為 VLM+LLM 護理術科評分系統執行測試並開發測試案例。

## 基本設定

我們的後端主要是使用 Python 與 FastAPI 撰寫，測試核心框架使用 `pytest` 配合 `httpx` (用於測試非同步 API 與 FastAPI `TestClient`)。

### 1. 安裝測試依賴
請確保您已安裝專案運行環境，並補充安裝下列測試用套件：
```bash
pip install pytest pytest-asyncio httpx websockets
```

### 2. 測試資料庫準備
為了避免污染正式資料庫，建議於本機端啟動一個測試專用的 PostgreSQL 容器（此步驟與 CI 環境同步）：
```bash
docker run --name vlm_test_db \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=vlm_eval_test \
  -p 5432:5432 -d postgres:15
```

### 3. 執行測試

#### 方式一：於 Docker 容器內執行（最推薦 ✨）
由於需要編譯 Rust (用於 asyncpg) 與資料庫連線等環境相依性考量，強烈建議直接在已啟動的 backend 容器內執行測試，省去本機的各種環境變數或套件問題。
請在專案根目錄確認已啟動服務後，直接於終端機下達（使用 Compose service 名稱，可避免綁定實際容器名稱）：
```bash
docker compose exec backend pytest
```
（註：測試容器會自動建立並切換至 `vlm_eval_test` 以保護正式資料）

#### 方式二：本機環境執行
在執行測試前，須將環境變數 `DATABASE_URL` 指向測試資料庫。可在終端機中使用以下指令執行：

**Windows (PowerShell):**
```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/vlm_eval_test"
pytest backend/tests/ -v
```

**Linux / Mac:**
```bash
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/vlm_eval_test" pytest backend/tests/ -v
```

## 測試目錄結構

請將測試檔案統一放置於 `backend/tests/` 目錄下：
```text
backend/
└── tests/
    ├── conftest.py          # 定義共用的 fixtures (例如 DB session 與 TestClient)
    ├── test_api.py          # REST API 測試 (GET/POST /evaluations 等)
    ├── test_ws.py           # WebSocket 測試 (推送機制)
    └── test_gemini.py       # (Mock) Gemini 服務單元測試
```

## 建立新測試範例

### 範例：測試 RESTful API
透過 `FastAPI` 提供的 `TestClient`，我們不僅測試 HTTP request，也能透過 `db_session` 驗證資料庫事件（Event-Driven）的生成：

```python
# backend/tests/test_api.py
import pytest
from app.models.evaluation import EvaluationJob, JobBranch

def test_create_evaluation(client, db_session):
    payload = {
        "student_id": "S112501",
        "exam_topic": "iv-injection",
        "video_paths": ["D:/Data/Videos/cam1.mp4"],
        "gemini_api_key": "AIzaSy..."
    }
    
    # 發起 API 請求建立新任務
    response = client.post("/api/v1/evaluations/", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["student_id"] == "S112501"
    
    # 驗證三個分支任務 (JobBranch) 是否一併被建立
    job_id = data["id"]
    branches = db_session.query(JobBranch).filter(JobBranch.job_id == job_id).all()
    assert len(branches) == 3
```

### 範例：測試 WebSocket 的連線
為了測試 WebSocket，我們需要先插入一筆暫存的 `EvaluationJob` 進資料庫，接著透過 `client.websocket_connect` 驗證連線是否成功。

```python
# backend/tests/test_ws.py
def test_websocket_connection(client, db_session):
    try:
        # 手動注入測試假資料
        job = EvaluationJob(id="test-job-ws-uuid", student_id="ws-test", status="pending")
        db_session.add(job)
        db_session.commit()

        # 連線 WebSocket 路由並發送 Ping
        with client.websocket_connect(f"/api/v1/evaluations/test-job-ws-uuid/ws") as websocket:
            websocket.send_text("ping")
            assert True
    except Exception as e:
        pytest.fail(f"WebSocket connection failed: {e}")
```

## GitHub Actions 自動化 CI
本專案已在 `.github/workflows/python-ci.yml` 設定了 CI 流程。
每次針對 `main` 分支的提交或 PR，均會自動：
1. 啟動一個 Postgres Test Database 容器。
2. 安裝所有開發與測試的相依模組。
3. 自動以該測試資料庫執行 `pytest backend/tests/ -v`，檢驗系統是否有功能崩壞。
