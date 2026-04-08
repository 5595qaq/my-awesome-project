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
    # 先建立一個評估任務以取得 job_id
    payload = {
        "student_id": "S112502",
        "exam_topic": "iv-injection",
        "video_paths": ["D:/Data/Videos/cam2.mp4"],
        "gemini_api_key": "dummy_api_key"
    }
    response = client.post("/api/v1/evaluations/", json=payload)
    job_id = response.json()["id"]

    # 測試連線 WebSocket
    with client.websocket_connect(f"/api/v1/evaluations/{job_id}/ws") as websocket:
        # Background task 可能會立刻開始傳送資料，這裡測試能否成功連線並等候到第一筆資訊
        data = websocket.receive_json()
        assert data["event"] == "STAGE_UPDATE"
        assert data["payload"]["stage"] == "GEMINI_UPLOAD"
