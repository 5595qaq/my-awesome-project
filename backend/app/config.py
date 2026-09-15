import os


class Settings:
    GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
    GCP_LOCATION = os.getenv("GCP_LOCATION", "global")
    GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "")
    GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-pro-preview")


settings = Settings()
