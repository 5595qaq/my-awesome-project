import uuid
from sqlalchemy import Column, String, JSON, ForeignKey
from app.db import Base

class EvaluationJob(Base):
    __tablename__ = "evaluation_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String, index=True)
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

