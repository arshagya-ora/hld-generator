"""
Authentication Schemas
Request and response models for auth endpoints
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
import uuid


class UserRegisterRequest(BaseModel):
    """Request schema for user registration"""
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=12, description="Password (min 12 characters)")
    full_name: Optional[str] = Field(None, max_length=255, description="User's full name")
    tenant_name: str = Field(..., min_length=2, max_length=255, description="Organization name")


class UserLoginRequest(BaseModel):
    """Request schema for user login"""
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="Password")


class TokenResponse(BaseModel):
    """Response schema for authentication tokens"""
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiration in seconds")


class RefreshTokenRequest(BaseModel):
    """Request schema for token refresh"""
    refresh_token: str = Field(..., description="JWT refresh token")


class UserResponse(BaseModel):
    """Response schema for user data"""
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]

    class Config:
        from_attributes = True  # Pydantic v2: enable ORM mode


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str
