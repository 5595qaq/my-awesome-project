import json
from pathlib import Path

from google import genai
from google.genai import types

from app.config import settings

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

AGENT_PROMPTS = {
    "Agent_B": (_PROMPTS_DIR / "Agent_B.txt").read_text(encoding="utf-8"),
    "Agent_C": (_PROMPTS_DIR / "Agent_C.txt").read_text(encoding="utf-8"),
    "Agent_D": (_PROMPTS_DIR / "Agent_D.txt").read_text(encoding="utf-8"),
}

AGENT_NAMES = list(AGENT_PROMPTS)

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
    """Runs a single agent's evaluation pass over one video via Vertex AI."""
    video_part = types.Part.from_uri(file_uri=video_uri, mime_type="video/mp4")
    prompt = f"Exam topic: {exam_topic}\n{AGENT_PROMPTS[agent_name]}"

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
