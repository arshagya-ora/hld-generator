"""
JWT Token Utilities
Generate and validate JWT access and refresh tokens
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from jose import JWTError, jwt
from config import settings


def create_access_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token

    Args:
        user_id: User's UUID
        tenant_id: Tenant's UUID
        email: User's email
        role: User's role (user, admin, super_admin)
        expires_delta: Optional custom expiration time

    Returns:
        JWT token string
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode = {
        "sub": str(user_id),  # Subject (user ID)
        "tenant_id": str(tenant_id),
        "email": email,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),  # Issued at
    }

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT refresh token

    Args:
        user_id: User's UUID
        tenant_id: Tenant's UUID
        expires_delta: Optional custom expiration time

    Returns:
        JWT refresh token string
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )

    to_encode = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT token

    Args:
        token: JWT token string

    Returns:
        Decoded token payload

    Raises:
        JWTError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        raise JWTError(f"Invalid token: {str(e)}")


def verify_token_type(payload: dict, expected_type: str) -> bool:
    """
    Verify that a token payload has the expected type

    Args:
        payload: Decoded token payload
        expected_type: Expected token type ("access" or "refresh")

    Returns:
        True if token type matches
    """
    return payload.get("type") == expected_type


def extract_user_id(payload: dict) -> uuid.UUID:
    """
    Extract user ID from token payload

    Args:
        payload: Decoded token payload

    Returns:
        User UUID

    Raises:
        ValueError: If user ID is missing or invalid
    """
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise ValueError("Token missing user ID")

    try:
        return uuid.UUID(user_id_str)
    except ValueError:
        raise ValueError("Invalid user ID in token")


def extract_tenant_id(payload: dict) -> uuid.UUID:
    """
    Extract tenant ID from token payload

    Args:
        payload: Decoded token payload

    Returns:
        Tenant UUID

    Raises:
        ValueError: If tenant ID is missing or invalid
    """
    tenant_id_str = payload.get("tenant_id")
    if not tenant_id_str:
        raise ValueError("Token missing tenant ID")

    try:
        return uuid.UUID(tenant_id_str)
    except ValueError:
        raise ValueError("Invalid tenant ID in token")
