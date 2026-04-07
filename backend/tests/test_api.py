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
