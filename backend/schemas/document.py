"""
Document Schemas
Request and response models for document endpoints
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid


class DocumentUploadResponse(BaseModel):
    """Response schema for document upload"""
    id: uuid.UUID = Field(..., description="Document ID")
    filename: str = Field(..., description="Internal filename")
    original_filename: str = Field(..., description="Original filename")
    file_size_bytes: int = Field(..., description="File size in bytes")
    mime_type: Optional[str] = Field(None, description="MIME type")
    document_type: str = Field(..., description="Document type (PID, RD, DIAGRAM, OTHER)")
    document_label: Optional[str] = Field(None, description="User-provided label")
    uploaded_at: datetime = Field(..., description="Upload timestamp")

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    """Response schema for document details"""
    id: uuid.UUID
    filename: str
    original_filename: str
    file_size_bytes: int
    file_size_mb: float = Field(..., description="File size in MB")
    mime_type: Optional[str]
    document_type: str
    document_label: Optional[str]
    cognee_dataset_name: Optional[str]
    uploaded_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Response schema for document list"""
    documents: List[DocumentResponse]
    count: int
    page: int = Field(default=1, description="Current page number")
    page_size: int = Field(default=20, description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")


class DocumentTypeUpdateRequest(BaseModel):
    """Request schema for updating document type and label"""
    document_type: str = Field(..., description="Document type (PID, RD, DIAGRAM, OTHER)")
    document_label: Optional[str] = Field(None, description="User-provided label")
