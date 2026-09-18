import io
import threading
import time
from pathlib import Path
from unittest.mock import patch


def _fake_convert(input_path, output_path):
    Path(output_path).write_bytes(b"converted")


def test_upload_skips_conversion_when_1fps_already_exists(client):
    with patch("app.services.gcs_service.blob_exists", return_value=True), \
         patch("app.services.video_service.convert_to_1fps") as mock_convert, \
         patch("app.services.video_service.convert_to_5fps") as mock_gaze_convert:
        response = client.post(
            "/api/v1/uploads/",
            files={"files": ("cam1.mp4", io.BytesIO(b"fake video bytes"), "video/mp4")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data[0]["filename"] == "cam1_1fps.mp4"
    assert data[0]["status"] == "skipped_existing"
    mock_convert.assert_not_called()
    mock_gaze_convert.assert_not_called()


def test_upload_converts_and_uploads_new_video(client):
    with patch("app.services.gcs_service.blob_exists", return_value=False), \
         patch("app.services.video_service.convert_to_1fps", side_effect=_fake_convert) as mock_convert, \
         patch("app.services.video_service.convert_to_5fps", side_effect=_fake_convert) as mock_gaze_convert, \
         patch(
             "app.services.gcs_service.upload_if_needed",
             return_value=("gs://bucket/cam2_1fps.mp4", "uploaded"),
         ) as mock_upload:
        response = client.post(
            "/api/v1/uploads/",
            files={"files": ("cam2.mp4", io.BytesIO(b"fake video bytes"), "video/mp4")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data[0]["filename"] == "cam2_1fps.mp4"
    assert data[0]["status"] == "uploaded"
    mock_convert.assert_called_once()
    mock_gaze_convert.assert_called_once()
    assert mock_upload.call_count == 2


def test_upload_rejects_1fps_file_when_gaze_source_is_missing(client):
    with patch("app.services.gcs_service.blob_exists", return_value=False), \
         patch("app.services.video_service.convert_to_1fps") as mock_convert, \
         patch(
             "app.services.gcs_service.upload_if_needed",
             return_value=("gs://bucket/cam3_1fps.mp4", "uploaded"),
         ):
        response = client.post(
            "/api/v1/uploads/",
            files={"files": ("cam3_1fps.mp4", io.BytesIO(b"already 1fps"), "video/mp4")},
        )

    assert response.status_code == 422
    mock_convert.assert_not_called()


def test_upload_processes_at_most_two_videos_in_parallel(client):
    lock = threading.Lock()
    active = 0
    max_active = 0

    def tracked_convert(input_path, output_path):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            Path(output_path).write_bytes(b"converted")
        finally:
            with lock:
                active -= 1

    def fake_upload(_file_obj, filename, _content_type):
        return f"gs://bucket/{filename}", "uploaded"

    files = [
        ("files", (f"cam{i}.mp4", io.BytesIO(b"video"), "video/mp4"))
        for i in range(3)
    ]
    with patch("app.services.gcs_service.blob_exists", return_value=False), \
         patch("app.services.video_service.convert_to_1fps", side_effect=tracked_convert), \
         patch("app.services.video_service.convert_to_5fps", side_effect=_fake_convert), \
         patch("app.services.gcs_service.upload_if_needed", side_effect=fake_upload):
        response = client.post("/api/v1/uploads/", files=files)

    assert response.status_code == 200
    assert max_active == 2


def test_parallel_upload_results_keep_input_order(client):
    completion_order = []

    def delayed_upload(_file_obj, filename, _content_type):
        if filename == "slow_1fps.mp4":
            time.sleep(0.05)
        if filename.endswith("_1fps.mp4"):
            completion_order.append(filename)
        return f"gs://bucket/{filename}", "uploaded"

    files = [
        ("files", ("slow.mp4", io.BytesIO(b"video"), "video/mp4")),
        ("files", ("fast.mp4", io.BytesIO(b"video"), "video/mp4")),
    ]
    with patch("app.services.gcs_service.blob_exists", return_value=False), \
         patch("app.services.video_service.convert_to_1fps", side_effect=_fake_convert), \
         patch("app.services.video_service.convert_to_5fps", side_effect=_fake_convert), \
         patch("app.services.gcs_service.upload_if_needed", side_effect=delayed_upload):
        response = client.post("/api/v1/uploads/", files=files)

    assert response.status_code == 200
    assert completion_order == ["fast_1fps.mp4", "slow_1fps.mp4"]
    assert [item["filename"] for item in response.json()] == [
        "slow_1fps.mp4",
        "fast_1fps.mp4",
    ]


def test_existing_video_skips_conversion_while_new_video_is_processed(client):
    def exists(filename):
        return filename in {"existing_1fps.mp4", "existing_gaze_5fps.mp4"}

    files = [
        ("files", ("existing.mp4", io.BytesIO(b"old"), "video/mp4")),
        ("files", ("new.mp4", io.BytesIO(b"new"), "video/mp4")),
    ]
    with patch("app.services.gcs_service.blob_exists", side_effect=exists), \
         patch("app.services.video_service.convert_to_1fps", side_effect=_fake_convert) as mock_convert, \
         patch("app.services.video_service.convert_to_5fps", side_effect=_fake_convert) as mock_gaze_convert, \
         patch(
             "app.services.gcs_service.upload_if_needed",
             return_value=("gs://bucket/new_1fps.mp4", "uploaded"),
         ) as mock_upload:
        response = client.post("/api/v1/uploads/", files=files)

    assert response.status_code == 200
    assert [item["status"] for item in response.json()] == [
        "skipped_existing",
        "uploaded",
    ]
    mock_convert.assert_called_once()
    mock_gaze_convert.assert_called_once()
    assert mock_upload.call_count == 2
