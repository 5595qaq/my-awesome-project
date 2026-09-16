import uuid
from sqlalchemy import Column, String, JSON, ForeignKey, Integer, Boolean, UniqueConstraint, CheckConstraint
from app.db import Base

class EvaluationJob(Base):
    __tablename__ = "evaluation_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    exam_topic = Column(String)
    processing_mode = Column(String) # standard or batch
    status = Column(String, default="pending") 
    video_paths = Column(JSON, default=list)
    result = Column(JSON, nullable=True)
    
class JobBranch(Base):
    __tablename__ = "job_branches"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("evaluation_jobs.id", ondelete="CASCADE"), index=True)
    branch_name = Column(String) # e.g. 'GEMINI_UPLOAD', 'GEMINI_PROCESSING', 'LLM_SCORING'
    status = Column(String, default="pending") # e.g. 'pending', 'in-progress', 'completed', 'failed'
    progress = Column(String, nullable=True) # e.g. '1/3'
    message = Column(String, nullable=True)


class EvaluationVideo(Base):
    __tablename__ = "evaluation_videos"
    __table_args__ = (UniqueConstraint("job_id", "position"),)

    id = Column(String, primary_key=True)
    job_id = Column(String, ForeignKey("evaluation_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    uri = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    segments = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    verified = Column(Boolean, nullable=False, default=False)


class EvaluationAgentRun(Base):
    __tablename__ = "evaluation_agent_runs"
    __table_args__ = (UniqueConstraint("video_id", "agent_name"),)

    id = Column(String, primary_key=True)
    video_id = Column(String, ForeignKey("evaluation_videos.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    result = Column(JSON, nullable=True)


class EvaluationProgress(Base):
    __tablename__ = "evaluation_progress"
    __table_args__ = (CheckConstraint("completed_steps >= 0 AND completed_steps <= total_steps"),)

    job_id = Column(String, ForeignKey("evaluation_jobs.id", ondelete="CASCADE"), primary_key=True)
    total_steps = Column(Integer, nullable=False)
    completed_steps = Column(Integer, nullable=False, default=0)

