from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict

class EvaluationCreate(BaseModel):
    student_id: str
    exam_topic: str
    processing_mode: str
    video_paths: List[str]
    gemini_api_key: str

class EvaluationResponse(BaseModel):
    id: str
    student_id: str
    exam_topic: str
    processing_mode: str
    status: str
    video_paths: List[str]
    result: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True
