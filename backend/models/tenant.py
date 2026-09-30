"""
Tenant Model
Root model for multi-tenancy - all other models reference this
"""
from sqlalchemy import Column, String, Integer, Boolean
from .base import BaseModel


class Tenant(BaseModel):
    """
    Tenant model - represents a company or organization
    """
    __tablename__ = "tenants"

    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    plan = Column(String(50), nullable=False, default="free")  # free, pro, enterprise
    max_users = Column(Integer, default=999999, nullable=False)  # No practical limit
    max_concurrent_jobs = Column(Integer, default=2, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<Tenant(id={self.id}, name={self.name}, slug={self.slug})>"
