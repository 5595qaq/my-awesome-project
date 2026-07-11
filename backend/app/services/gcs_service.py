from google.cloud import storage

from app.config import settings

_client = None


def get_client():
    global _client
    if _client is None:
        _client = storage.Client(project=settings.GCP_PROJECT_ID)
    return _client


def gcs_uri_for(filename: str) -> str:
    return f"gs://{settings.GCS_BUCKET_NAME}/{filename}"


def blob_exists(filename: str) -> bool:
    bucket = get_client().bucket(settings.GCS_BUCKET_NAME)
    return bucket.blob(filename).exists()


def parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// URI: {gcs_uri}")
    bucket_name, _, object_name = gcs_uri[len("gs://"):].partition("/")
    return bucket_name, object_name


def blob_exists_at_uri(gcs_uri: str) -> bool:
    # Unlike blob_exists(), this resolves against whatever bucket the URI
    # itself names, so manually-pasted gs:// paths from other buckets work too.
    bucket_name, object_name = parse_gcs_uri(gcs_uri)
    return get_client().bucket(bucket_name).blob(object_name).exists()


def upload_if_needed(file_obj, filename: str, content_type: str | None = None) -> tuple[str, str]:
    """Uploads file_obj to GCS under `filename` unless a blob with that name
    already exists, in which case the existing object is reused as-is.
    Dedup is by filename only (not content hash), per project decision.
    """
    bucket = get_client().bucket(settings.GCS_BUCKET_NAME)
    blob = bucket.blob(filename)

    if blob.exists():
        return gcs_uri_for(filename), "skipped_existing"

    blob.upload_from_file(file_obj, content_type=content_type)
    return gcs_uri_for(filename), "uploaded"
