"""
User Model
User accounts with authentication and RBAC
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .compat_types import UUID
from .base import TenantIsolatedModel


class User(TenantIsolatedModel):
    """
    User model with authentication and role-based access control
    """
    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    role = Column(String(50), nullable=False, default="user")  # user, admin, super_admin
    is_active = Column(Boolean, default=True, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime(timezone=True))

    # Relationships
    # documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    # jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"

    @property
    def full_name(self) -> str:
        """Get user's full name"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.email.split('@')[0]

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission based on role"""
        permissions = {
            "super_admin": ["*"],  # All permissions
            "admin": [
                "view_all_jobs",
                "manage_users",
                "view_metrics",
                "manage_tenant_settings"
            ],
            "user": [
                "create_job",
                "view_own_jobs",
                "manage_own_profile"
            ]
        }

        role_permissions = permissions.get(self.role, [])
        return "*" in role_permissions or permission in role_permissions


# ============================================================================
# User Deletion File Cleanup
# ============================================================================
# SQLAlchemy event listener to clean up files before user deletion
# This runs BEFORE the database CASCADE, so we can still access related documents
# ============================================================================

from sqlalchemy import event
from pathlib import Path
import shutil
import logging

logger = logging.getLogger(__name__)


@event.listens_for(User, 'before_delete')
def cleanup_user_files(mapper, connection, target):
    """
    Clean up all files associated with a user before cascading delete.

    This runs BEFORE the database CASCADE, so we can still access related documents.
    Deletes:
    - All encrypted document files for this user
    - User's entire document directory
    """
    from sqlalchemy.orm import Session
    from backend.models.document import Document
    from backend.config import get_settings

    settings = get_settings()
    session = Session(bind=connection)

    try:
        # Get all documents for this user
        documents = session.query(Document).filter(Document.user_id == target.id).all()

        files_deleted = 0
        for doc in documents:
            # Delete encrypted file from storage
            if doc.storage_path:
                storage_path = Path(doc.storage_path)
                if storage_path.exists():
                    try:
                        storage_path.unlink()
                        files_deleted += 1
                        logger.info(f"Deleted document file for user {target.id}: {storage_path}")
                    except Exception as e:
                        logger.warning(f"Failed to delete document file {storage_path}: {e}")

        # Delete user's entire document directory if it exists
        user_doc_dir = Path(settings.STORAGE_PATH) / "documents" / str(target.tenant_id) / str(target.id)
        if user_doc_dir.exists():
            try:
                shutil.rmtree(user_doc_dir)
                logger.info(f"Deleted user document directory: {user_doc_dir}")
            except Exception as e:
                logger.warning(f"Failed to delete user directory {user_doc_dir}: {e}")

        logger.info(f"✓ User cleanup complete for user {target.id}: {files_deleted} files deleted")

    except Exception as e:
        logger.error(f"Error cleaning up files for user {target.id}: {e}")
        # Don't fail the deletion, but log it
