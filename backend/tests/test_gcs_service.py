import io
from unittest.mock import MagicMock, patch

from app.services import gcs_service


def _fake_client(exists: bool):
    blob = MagicMock()
    blob.exists.return_value = exists
    bucket = MagicMock()
    bucket.blob.return_value = blob
    client = MagicMock()
    client.bucket.return_value = bucket
    return client, blob


def test_upload_if_needed_skips_existing_filename():
    client, blob = _fake_client(exists=True)

    with patch.object(gcs_service, "get_client", return_value=client):
        uri, status = gcs_service.upload_if_needed(io.BytesIO(b"data"), "cam1.mp4")

    assert status == "skipped_existing"
    assert uri.endswith("/cam1.mp4")
    blob.upload_from_file.assert_not_called()


def test_upload_if_needed_uploads_new_filename():
    client, blob = _fake_client(exists=False)

    with patch.object(gcs_service, "get_client", return_value=client):
        uri, status = gcs_service.upload_if_needed(io.BytesIO(b"data"), "cam2.mp4")

    assert status == "uploaded"
    assert uri.endswith("/cam2.mp4")
    blob.upload_from_file.assert_called_once()


def test_blob_exists_at_uri_parses_bucket_from_uri():
    client, blob = _fake_client(exists=True)

    with patch.object(gcs_service, "get_client", return_value=client):
        result = gcs_service.blob_exists_at_uri("gs://some-other-bucket/1/video.mp4")

    assert result is True
    client.bucket.assert_called_once_with("some-other-bucket")
    client.bucket.return_value.blob.assert_called_once_with("1/video.mp4")
