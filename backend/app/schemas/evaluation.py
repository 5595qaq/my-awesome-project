from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict

class EvaluationCreate(BaseModel):
    exam_topic: str
    video_paths: List[str]  # gs:// URIs
    processing_mode: Optional[str] = Field(default="standard")

class EvaluationResponse(BaseModel):
    id: str
    exam_topic: str
    status: str
    video_paths: List[str]
    result: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True
