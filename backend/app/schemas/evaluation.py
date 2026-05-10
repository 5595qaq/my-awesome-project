from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict

class EvaluationCreate(BaseModel):
    student_id: str
    exam_topic: str
    video_paths: List[str]
    gemini_api_key: str
    processing_mode: Optional[str] = Field(default="standard")

class EvaluationResponse(BaseModel):
    id: str
    student_id: str
    exam_topic: str
    status: str
    video_paths: List[str]
    result: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True
