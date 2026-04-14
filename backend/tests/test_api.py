import pytest
from app.models.evaluation import EvaluationJob, JobBranch

def test_create_evaluation(client, db_session):
    payload = {
        "student_id": "S112501",
        "exam_topic": "iv-injection",
        "video_paths": ["D:/Data/Videos/cam1.mp4"],
        "gemini_api_key": "dummy_api_key"
    }

    # 發起 API 請求建立新任務
    response = client.post("/api/v1/evaluations/", json=payload)

    # 驗證 Response 與初始狀態
    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == "S112501"
    assert data["exam_topic"] == "iv-injection"
    assert data["status"] == "pending"
    assert "id" in data
    
    job_id = data["id"]
    
    # 驗證資料庫是否正確儲存主任務 (Job)
    job_in_db = db_session.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
    assert job_in_db is not None
    assert job_in_db.status == "pending"
    
    # 驗證三個分支任務 (JobBranch) 是否一併被建立並設為 pending
    branches = db_session.query(JobBranch).filter(JobBranch.job_id == job_id).all()
    assert len(branches) == 3
    
    branch_names = [b.branch_name for b in branches]
    assert "GEMINI_UPLOAD" in branch_names
    assert "GEMINI_PROCESSING" in branch_names
    assert "LLM_SCORING" in branch_names
    
    for branch in branches:
        assert branch.status == "pending"

def test_websocket_connection(client, db_session):
    try:
        job = EvaluationJob(id="test-job-ws-123", student_id="ws-test", status="pending")
        db_session.add(job)
        db_session.commit()

        # 測試連線 WebSocket 路由
        with client.websocket_connect(f"/api/v1/evaluations/test-job-ws-123/ws") as websocket:
            # 傳遞 Ping 並未斷線代表路由與 ConnectionManager 工作正常
            websocket.send_text("ping")
            assert True
    except Exception as e:
        pytest.fail(f"WebSocket connection failed: {e}")
import pytest
from unittest.mock import patch
from app.models.evaluation import EvaluationJob, JobBranch

def test_create_evaluation(client, db_session):
    payload = {
        "student_id": "S112501",
        "exam_topic": "iv-injection",
        "video_paths": ["D:/Data/Videos/cam1.mp4"],
        "gemini_api_key": "dummy_api_key"
    }

    # 發起 API 請求建立新任務
    response = client.post("/api/v1/evaluations/", json=payload)

    # 驗證 Response 與初始狀態
    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == "S112501"
    assert data["exam_topic"] == "iv-injection"
    assert data["status"] == "pending"
    assert "id" in data
    
    job_id = data["id"]
    
    # 驗證資料庫是否正確儲存主任務 (Job)
    job_in_db = db_session.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
    assert job_in_db is not None
    assert job_in_db.status == "pending"
    
    # 驗證三個分支任務 (JobBranch) 是否一併被建立並設為 pending
    branches = db_session.query(JobBranch).filter(JobBranch.job_id == job_id).all()
    assert len(branches) == 3
    
    branch_names = [b.branch_name for b in branches]
    assert "GEMINI_UPLOAD" in branch_names
    assert "GEMINI_PROCESSING" in branch_names
    assert "LLM_SCORING" in branch_names
    
    for branch in branches:
        assert branch.status == "pending"

def test_websocket_connection(client, db_session):
    try:
        job = EvaluationJob(id="test-job-ws-123", student_id="ws-test", status="pending")
        db_session.add(job)
        db_session.commit()

        # 測試連線 WebSocket 路由
        with client.websocket_connect(f"/api/v1/evaluations/test-job-ws-123/ws") as websocket:
            # 傳遞 Ping 並未斷線代表路由與 ConnectionManager 工作正常
            websocket.send_text("ping")
            assert True
    except Exception as e:
        pytest.fail(f"WebSocket connection failed: {e}")

import pytest
from unittest.mock import patch
from app.models.evaluation import EvaluationJob, JobBranch

def test_create_evaluation(client, db_session):
    payload = {
        "student_id": "S112501",
        "exam_topic": "iv-injection",
        "video_paths": ["D:/Data/Videos/cam1.mp4"],
        "gemini_api_key": "dummy_api_key"
    }

    # 發起 API 請求建立新任務
    response = client.post("/api/v1/evaluations/", json=payload)

    # 驗證 Response 與初始狀態
    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == "S112501"
    assert data["exam_topic"] == "iv-injection"
    assert data["status"] == "pending"
    assert "id" in data
    
    job_id = data["id"]
    
    # 驗證資料庫是否正確儲存主任務 (Job)
    job_in_db = db_session.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
    assert job_in_db is not None
    assert job_in_db.status == "pending"
    
    # 驗證三個分支任務 (JobBranch) 是否一併被建立並設為 pending
    branches = db_session.query(JobBranch).filter(JobBranch.job_id == job_id).all()
    assert len(branches) == 3
    
    branch_names = [b.branch_name for b in branches]
    assert "GEMINI_UPLOAD" in branch_names
    assert "GEMINI_PROCESSING" in branch_names
    assert "LLM_SCORING" in branch_names
    
    for branch in branches:
        assert branch.status == "pending"

def test_websocket_connection(client, db_session):
    try:
        # 測試連線 WebSocket 路由
        with client.websocket_connect(f"/api/v1/evaluations/test-job-ws-123/ws") as websocket:
            # 傳遞 Ping 並未斷線代表路由與 ConnectionManager 工作正常
            websocket.send_text("ping")
            assert True
    except Exception as e:
        pytest.fail(f"WebSocket connection failed: {e}")
