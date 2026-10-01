"""
Base SQLAlchemy Model
Provides tenant isolation and common fields for all models
"""
from sqlalchemy import Column, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from .compat_types import UUID
import uuid
from datetime import datetime

Base = declarative_base()


class TenantIsolatedModel(Base):
    """
    Abstract base model with tenant isolation
    All models inheriting from this will have Row-Level Security enforced
    """
    __abstract__ = True

    id = Column(UUID(), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id})>"

    def to_dict(self):
        """Convert model to dictionary"""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }


class BaseModel(Base):
    """
    Base model without tenant isolation
    Use for models that don't need multi-tenancy (e.g., tenants table itself)
    """
    __abstract__ = True

    id = Column(UUID(), primary_key=True, default=uuid.uuid4, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id})>"

    def to_dict(self):
        """Convert model to dictionary"""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }
