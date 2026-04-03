from locust import HttpUser, task, between

class VLMSystemUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def create_eval_job(self):
        payload = {
            "student_id": "S112501",
            "exam_topic": "iv-injection",
            "processing_mode": "standard",
            "video_paths": ["D:/Data/Videos/cam1.mp4"],
            "gemini_api_key": "dummy_api_key"
        }
        self.client.post("/api/v1/evaluations/", json=payload)
