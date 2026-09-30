"""
Authentication API Routes
Register, login, logout, token refresh
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import uuid

from database import get_db
from schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserResponse,
    MessageResponse
)
from models.tenant import Tenant
from models.user import User
from auth.password import hash_password, verify_password, validate_password_complexity
from auth.jwt import create_access_token, create_refresh_token, decode_token, verify_token_type
from auth.dependencies import get_current_user
from config import settings

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: UserRegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user and create a tenant

    - Creates a new tenant (organization) if it doesn't exist
    - Creates a user account with admin role (first user in tenant)
    - Returns user details
    """
    # Validate password complexity
    is_valid, error_msg = validate_password_complexity(request.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == request.email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create tenant slug from name
    tenant_slug = request.tenant_name.lower().replace(" ", "-").replace("_", "-")

    # Check if tenant slug exists (handle concurrent registration race)
    result = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    tenant = result.scalar_one_or_none()

    if not tenant:
        # Create new tenant — wrap in try/except for duplicate slug race condition
        tenant = Tenant(
            name=request.tenant_name,
            slug=tenant_slug,
            plan="free",
            max_users=999999,  # No practical limit
            max_concurrent_jobs=2,
            is_active=True
        )
        db.add(tenant)
        try:
            await db.flush()  # Flush to get tenant.id
        except Exception:
            # Another concurrent request likely created the same tenant
            await db.rollback()
            result = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
            tenant = result.scalar_one_or_none()
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create tenant. Please try again."
                )

    # Check tenant user limit before adding new user
    from sqlalchemy import func as sa_func
    user_count_result = await db.execute(
        select(sa_func.count()).select_from(User).where(User.tenant_id == tenant.id)
    )
    user_count = user_count_result.scalar()

    if user_count >= tenant.max_users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tenant '{tenant.name}' has reached its user limit ({tenant.max_users}). "
                   f"Contact an administrator to increase the limit."
        )

    user_role = "admin" if user_count == 0 else "user"

    # Split full_name into first_name / last_name
    name_parts = (request.full_name or "").split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    user = User(
        tenant_id=tenant.id,
        email=request.email,
        password_hash=hash_password(request.password),
        first_name=first_name,
        last_name=last_name,
        role=user_role,
        is_active=True
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    request: UserLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Login with email and password

    - Validates credentials
    - Returns access and refresh tokens
    - Updates last_login_at timestamp
    """
    # Find user by email
    result = await db.execute(
        select(User).where(
            User.email == request.email,
            User.is_active == True
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login timestamp
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    # Generate tokens
    access_token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role
    )

    refresh_token = create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token using refresh token

    - Validates refresh token
    - Issues new access and refresh tokens
    """
    try:
        payload = decode_token(request.refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify token type
    if not verify_token_type(payload, "refresh"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract user ID
    user_id_str = payload.get("sub")
    tenant_id_str = payload.get("tenant_id")

    if not user_id_str or not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    user_id = uuid.UUID(user_id_str)
    tenant_id = uuid.UUID(tenant_id_str)

    # Fetch user
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.is_active == True
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    # Generate new tokens
    access_token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role
    )

    new_refresh_token = create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    Get current user information

    - Requires authentication
    - Returns user details
    """
    return current_user


@router.post("/logout", response_model=MessageResponse)
async def logout(
    current_user: User = Depends(get_current_user)
):
    """
    Logout current user

    - Requires authentication
    - In production, add token to Redis blacklist
    - Returns success message
    """
    # TODO: Add token to Redis blacklist in production
    # For now, client should discard tokens

    return MessageResponse(message="Successfully logged out")
