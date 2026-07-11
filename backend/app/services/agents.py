import json

from google import genai
from google.genai import types

from app.config import settings

# TODO: replace with the real agent roster + per-agent prompts once supplied.
AGENT_NAMES = ["Agent_B", "Agent_C"]

_PLACEHOLDER_PROMPT = (
    "Watch this nursing skills exam video and return a JSON array. "
    "Each element must describe one evaluated step of the procedure."
)

_client = None


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True,
            project=settings.GCP_PROJECT_ID,
            location=settings.GCP_LOCATION,
        )
    return _client


def run_agent(video_uri: str, agent_name: str, exam_topic: str) -> list[dict]:
    """Runs a single agent's evaluation pass over one video via Vertex AI.

    This is the single extension point for the real multi-agent nursing-eval
    prompts: swap _PLACEHOLDER_PROMPT (and the parsing below, if the real
    prompts need it) once they're available. Everything else in the pipeline
    (GCS wiring, progress reporting, result storage) stays as-is.
    """
    video_part = types.Part.from_uri(file_uri=video_uri, mime_type="video/mp4")
    prompt = f"Exam topic: {exam_topic}\n{_PLACEHOLDER_PROMPT}"

    response = get_client().models.generate_content(
        model=settings.GEMINI_MODEL_NAME,
        contents=[video_part, prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    parsed = json.loads(response.text)
    if isinstance(parsed, dict):
        parsed = [parsed]

    for item in parsed:
        item.setdefault("Video_Path", video_uri)
        item.setdefault("Agent_Name", agent_name)

    return parsed
