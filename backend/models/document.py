"""
Document Model
Uploaded source documents (PID, RDs, etc.)
"""
from sqlalchemy import Column, String, BigInteger, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from .compat_types import UUID, JSONB
from .base import TenantIsolatedModel


class Document(TenantIsolatedModel):
    """
    Document model - stores metadata for uploaded documents
    Files are encrypted and stored on disk
    """
    __tablename__ = "documents"

    user_id = Column(UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)  # Internal filename (UUID-based)
    original_filename = Column(String(255), nullable=False)  # User's original filename
    file_size_bytes = Column(BigInteger, nullable=False)
    mime_type = Column(String(100))
    storage_path = Column(String(512), nullable=False)  # Path to encrypted file
    document_type = Column(String(50), default="OTHER")  # PID, RD, DIAGRAM, OTHER
    document_label = Column(String(255))  # User-provided label
    cognee_dataset_name = Column(String(255))  # Cognee knowledge graph dataset
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    file_metadata = Column(JSONB)  # Document analysis results, extraction metadata

    # Relationships
    # user = relationship("User", back_populates="documents")
    # job_documents = relationship("JobDocument", back_populates="document", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Document(id={self.id}, filename={self.original_filename}, type={self.document_type})>"

    @property
    def size_mb(self) -> float:
        """Get file size in MB"""
        return round(self.file_size_bytes / (1024 * 1024), 2)
