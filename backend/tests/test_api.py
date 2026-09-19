import pytest

from app.models.evaluation import EvaluationJob, JobBranch
from app.services import gcs_service

def test_create_evaluation(client, db_session):
    payload = {
        "exam_topic": "iv-injection",
        "video_paths": ["gs://vlm_on99/1/cam1.mp4"],
    }

    # 發起 API 請求建立新任務
    response = client.post("/api/v1/evaluations/", json=payload)

    # 驗證 Response 與初始狀態
    assert response.status_code == 200
    data = response.json()
    assert data["exam_topic"] == "iv-injection"
    assert data["status"] == "pending"
    assert "id" in data

    job_id = data["id"]

    # 驗證資料庫是否正確儲存主任務 (Job)
    job_in_db = db_session.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
    assert job_in_db is not None
    assert job_in_db.status == "pending"

    # 驗證四個分支任務 (JobBranch) 是否一併被建立並設為 pending
    branches = db_session.query(JobBranch).filter(JobBranch.job_id == job_id).all()
    assert len(branches) == 4

    branch_names = [b.branch_name for b in branches]
    assert "GEMINI_UPLOAD" in branch_names
    assert "GEMINI_PROCESSING" in branch_names
    assert "GAZE_PROCESSING" in branch_names
    assert "LLM_SCORING" in branch_names

    for branch in branches:
        assert branch.status == "pending"

def test_websocket_connection(client, db_session):
    job = EvaluationJob(id="test-job-ws-123", exam_topic="iv-injection", status="pending")
    db_session.add(job)
    db_session.commit()

    try:
        # 測試連線 WebSocket 路由
        with client.websocket_connect("/api/v1/evaluations/test-job-ws-123/ws") as websocket:
            # 傳遞 Ping 並未斷線代表路由與 ConnectionManager 工作正常
            websocket.send_text("ping")
            assert True
    except Exception as e:
        pytest.fail(f"WebSocket connection failed: {e}")


def test_empty_videos_rejected(client):
    response = client.post("/api/v1/evaluations/", json={"exam_topic": "exam", "video_paths": []})
    assert response.status_code == 422


def test_more_than_ten_videos_accepted(client):
    response = client.post("/api/v1/evaluations/", json={
        "exam_topic": "exam", "video_paths": [f"gs://bucket/{i}.mp4" for i in range(23)],
    })
    assert response.status_code == 200
    assert len(response.json()["video_paths"]) == 23


def test_create_rejects_missing_video_source(client, monkeypatch, db_session):
    monkeypatch.setattr(gcs_service, "blob_exists_at_uri", lambda _uri: False)

    response = client.post("/api/v1/evaluations/", json={
        "exam_topic": "exam",
        "video_paths": ["gs://bucket/video_5fps.mp4"],
    })

    assert response.status_code == 422
    assert response.json()["detail"] == \
        "5 FPS video source does not exist: gs://bucket/video_5fps.mp4"
    assert db_session.query(EvaluationJob).count() == 0


def test_create_uses_the_single_existing_video_source(client, monkeypatch, db_session):
    checked = []
    monkeypatch.setattr(gcs_service, "blob_exists_at_uri", lambda uri: checked.append(uri) or True)

    response = client.post("/api/v1/evaluations/", json={
        "exam_topic": "exam",
        "video_paths": ["gs://source-bucket/video_5fps.mp4"],
    })

    assert response.status_code == 200
    assert checked == ["gs://source-bucket/video_5fps.mp4"]


def test_create_rejects_removed_gaze_source_paths(client):
    response = client.post("/api/v1/evaluations/", json={
        "exam_topic": "exam",
        "video_paths": ["gs://bucket/video_5fps.mp4"],
        "gaze_source_paths": {"unused": "gs://bucket/old.mp4"},
    })
    assert response.status_code == 422


def test_retry_missing_job_returns_404(client):
    response = client.post("/api/v1/evaluations/missing/retry")
    assert response.status_code == 404


def test_retry_active_job_returns_409(client):
    created = client.post("/api/v1/evaluations/", json={
        "exam_topic": "exam", "video_paths": ["gs://bucket/video.mp4"],
    }).json()
    response = client.post(f"/api/v1/evaluations/{created['id']}/retry")
    assert response.status_code == 409


def test_retry_retired_job_returns_409(client, db_session):
    job = EvaluationJob(id="retired-job", status="retired", result={"error": "upgrade"})
    db_session.add(job)
    db_session.commit()

    response = client.post("/api/v1/evaluations/retired-job/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == "Only failed evaluations can be retried"
