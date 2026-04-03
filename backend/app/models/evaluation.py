import uuid
from sqlalchemy import Column, String, JSON
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
    
    # Store API key temporally or just in-memory dict. Let's keep it in a global dict in-memory to avoid DB persistence
