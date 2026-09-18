import os


def _integer(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


class Settings:
    GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
    GCP_LOCATION = os.getenv("GCP_LOCATION", "global")
    GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "")
    GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-pro-preview")
    MAX_ACTIVE_VIDEOS_PER_EVALUATION = _integer("MAX_ACTIVE_VIDEOS_PER_EVALUATION", 10)
    GEMINI_GLOBAL_CONCURRENCY = _integer("GEMINI_GLOBAL_CONCURRENCY", 5)
    GEMINI_CALL_STAGGER_MS = _integer("GEMINI_CALL_STAGGER_MS", 250, 0)
    GEMINI_RETRY_ATTEMPTS = _integer("GEMINI_RETRY_ATTEMPTS", 5)
    GEMINI_QUEUE_RETRY_BASE_SECONDS = _integer("GEMINI_QUEUE_RETRY_BASE_SECONDS", 60)
    GEMINI_QUEUE_RETRY_MAX_SECONDS = _integer("GEMINI_QUEUE_RETRY_MAX_SECONDS", 900)

    if GEMINI_QUEUE_RETRY_MAX_SECONDS < GEMINI_QUEUE_RETRY_BASE_SECONDS:
        raise ValueError(
            "GEMINI_QUEUE_RETRY_MAX_SECONDS must be >= GEMINI_QUEUE_RETRY_BASE_SECONDS"
        )


settings = Settings()
