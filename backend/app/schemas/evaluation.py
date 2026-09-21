from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Any, Dict, Literal

AgentName = Literal["Agent_A", "Agent_B", "Agent_C", "Agent_D"]

class EvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exam_topic: str
    video_paths: List[str] = Field(min_length=1)  # gs:// URIs; excess videos queue in PostgreSQL
    processing_mode: Optional[str] = Field(default="standard")
    selected_agents: List[AgentName] = Field(default_factory=lambda: ["Agent_A", "Agent_B", "Agent_C", "Agent_D"], min_length=1)

    @field_validator("selected_agents")
    @classmethod
    def unique_agents(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("selected_agents must not contain duplicates")
        return value

class EvaluationResponse(BaseModel):
    id: str
    exam_topic: str
    status: str
    video_paths: List[str]
    selected_agents: List[AgentName] = Field(default_factory=lambda: ["Agent_A", "Agent_B", "Agent_C", "Agent_D"])
    result: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)
