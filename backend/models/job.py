"""
Job Model
HLD generation jobs and job-document relationships
"""
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from .compat_types import UUID, JSONB
from .base import TenantIsolatedModel, BaseModel


class Job(TenantIsolatedModel):
    """
    Job model - HLD generation jobs
    Tracks status, progress, and results
    """
    __tablename__ = "jobs"

    user_id = Column(UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(100), nullable=False)  # e.g., '5G_SBA', 'DSR'
    product_profile_file = Column(String(255))
    user_prompt = Column(Text, default="")  # Free-form user instructions for intent-driven generation

    # Job status
    status = Column(String(50), nullable=False, default="queued", index=True)
    # Possible values: queued, running, completed, failed, cancelled

    celery_task_id = Column(String(255), unique=True, index=True)  # Celery task UUID

    # Configuration
    config = Column(JSONB, nullable=False, default=dict)  # Job parameters (use callable to avoid shared mutable default)

    # State tracking (checkpoint for resume)
    current_state = Column(JSONB)  # Latest HLDGeneratorState
    pipeline_stage = Column(String(50))  # Current stage: analyzing, planning, generating, etc.
    progress_percent = Column(Integer, default=0)

    # Results
    output_path = Column(String(512))  # Path to generated HLD (DOCX)
    output_format = Column(String(20), default="docx")  # Only docx supported

    # Timing
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Error tracking
    error_message = Column(Text)
    error_traceback = Column(Text)

    # Metadata (execution metrics, LLM stats, etc.)
    job_metadata = Column(JSONB)

    # Relationships
    # user = relationship("User", back_populates="jobs")
    # job_documents = relationship("JobDocument", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Job(id={self.id}, product={self.product_id}, status={self.status})>"

    @property
    def duration_seconds(self) -> int:
        """Calculate job duration in seconds"""
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return 0


class JobDocument(BaseModel):
    """
    Many-to-many relationship between jobs and documents
    Allows multiple documents per job
    """
    __tablename__ = "job_documents"
    __table_args__ = (
        UniqueConstraint('job_id', 'document_id', name='uq_job_document'),
    )

    job_id = Column(UUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(UUID(), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    document_order = Column(Integer, nullable=False, default=0)  # Processing order

    # Relationships
    # job = relationship("Job", back_populates="job_documents")
    # document = relationship("Document", back_populates="job_documents")

    def __repr__(self):
        return f"<JobDocument(job_id={self.job_id}, document_id={self.document_id}, order={self.document_order})>"
