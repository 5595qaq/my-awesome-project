from unittest.mock import patch
from fastapi import BackgroundTasks

def test_create_evaluation(client):
    payload = {
        "student_id": "S112501",
        "exam_topic": "iv-injection",
        "video_paths": ["D:/Data/Videos/cam1.mp4"],
        "gemini_api_key": "dummy_api_key"
    }
    
    response = client.post("/api/v1/evaluations/", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == "S112501"
    assert data["exam_topic"] == "iv-injection"
    assert data["status"] == "pending"
    assert "id" in data
    assert data["id"] is not None

def test_websocket_connection(client):
    # 使用 mock 攔截背景任務，避免在 TestClient 的 post 中同步執行完畢
    with patch.object(BackgroundTasks, 'add_task') as mock_add_task:
        payload = {
            "student_id": "S112502",
            "exam_topic": "iv-injection",
            "video_paths": ["D:/Data/Videos/cam2.mp4"],
            "gemini_api_key": "dummy_api_key"
        }
        response = client.post("/api/v1/evaluations/", json=payload)
        job_id = response.json()["id"]

        # 確認的確有派發任務到背景
        assert mock_add_task.called

    # 測試連線 WebSocket
    with client.websocket_connect(f"/api/v1/evaluations/{job_id}/ws") as websocket:
        # 在 TestClient 中，由於後端任務已經被 Mock 而沒有執行，
        # 我們只要驗證連線沒有報錯斷開即可
        websocket.send_text("ping")
