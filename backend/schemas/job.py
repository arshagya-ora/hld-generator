"""
Job Schemas
Request and response models for HLD generation jobs
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid


class JobCreateRequest(BaseModel):
    """Request schema for creating a new HLD generation job"""
    product_id: str = Field(..., description="Product ID (e.g., '5G_SBA')")
    document_ids: List[uuid.UUID] = Field(..., min_length=1, description="List of document IDs to process")
    user_prompt: str = Field(
        default="",
        description="Free-form user instructions for HLD generation (e.g., 'Include only BSF and SCP. Use IPs from network plan.')"
    )
    config: Dict[str, Any] = Field(
        default_factory=lambda: {
            "output_format": "docx",
            "include_diagrams": True,
            "verbosity": "medium"
        },
        description="Job configuration"
    )


class JobResponse(BaseModel):
    """Response schema for job details"""
    id: uuid.UUID
    user_id: uuid.UUID
    product_id: str
    product_profile_file: Optional[str]
    status: str = Field(..., description="Job status (queued, running, completed, failed, cancelled)")
    celery_task_id: Optional[str]
    pipeline_stage: Optional[str] = Field(None, description="Current pipeline stage")
    progress_percent: int = Field(..., description="Progress percentage (0-100)")
    download_available: bool = Field(False, description="Whether a generated HLD can be downloaded")
    output_format: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    # Computed fields
    document_count: int = Field(default=0, description="Number of documents in job")
    duration_seconds: Optional[int] = Field(None, description="Job duration in seconds")

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    """Response schema for job list"""
    jobs: List[JobResponse]
    count: int
    page: int = Field(default=1)
    page_size: int = Field(default=20)
    total_pages: int


class JobDetailResponse(JobResponse):
    """Extended response schema with additional details"""
    config: Dict[str, Any]
    job_metadata: Optional[Dict[str, Any]] = Field(None, description="Execution metrics")
    documents: List[Dict[str, Any]] = Field(default_factory=list, description="Associated documents")


class JobStatusResponse(BaseModel):
    """Lightweight response for job status polling"""
    id: uuid.UUID
    status: str
    pipeline_stage: Optional[str]
    progress_percent: int
    error_message: Optional[str]


class PipelineStageUpdate(BaseModel):
    """Schema for pipeline stage updates (WebSocket messages)"""
    job_id: uuid.UUID
    stage: str = Field(..., description="Pipeline stage name")
    status: str = Field(..., description="Stage status (started, in_progress, completed, failed)")
    progress_percent: int
    message: Optional[str] = Field(None, description="Stage-specific message")
    agent_activity: Optional[str] = Field(None, description="Current agent activity (thinking, planning, etc.)")
    timestamp: datetime
