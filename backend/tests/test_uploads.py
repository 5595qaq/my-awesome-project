import io
from pathlib import Path
from unittest.mock import patch


def _fake_convert(input_path, output_path):
    Path(output_path).write_bytes(b"converted")


def test_upload_skips_conversion_when_1fps_already_exists(client):
    with patch("app.services.gcs_service.blob_exists", return_value=True), \
         patch("app.services.video_service.convert_to_1fps") as mock_convert:
        response = client.post(
            "/api/v1/uploads/",
            files={"files": ("cam1.mp4", io.BytesIO(b"fake video bytes"), "video/mp4")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data[0]["filename"] == "cam1_1fps.mp4"
    assert data[0]["status"] == "skipped_existing"
    mock_convert.assert_not_called()


def test_upload_converts_and_uploads_new_video(client):
    with patch("app.services.gcs_service.blob_exists", return_value=False), \
         patch("app.services.video_service.convert_to_1fps", side_effect=_fake_convert) as mock_convert, \
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
    mock_upload.assert_called_once()


def test_upload_skips_conversion_for_already_1fps_filename(client):
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

    assert response.status_code == 200
    data = response.json()
    assert data[0]["filename"] == "cam3_1fps.mp4"
    mock_convert.assert_not_called()
