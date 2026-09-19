from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any, Dict

class EvaluationCreate(BaseModel):
    exam_topic: str
    video_paths: List[str] = Field(min_length=1)  # gs:// URIs; excess videos queue in PostgreSQL
    processing_mode: Optional[str] = Field(default="standard")
    gaze_source_paths: Dict[str, str] = Field(default_factory=dict)

class EvaluationResponse(BaseModel):
    id: str
    exam_topic: str
    status: str
    video_paths: List[str]
    result: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)
