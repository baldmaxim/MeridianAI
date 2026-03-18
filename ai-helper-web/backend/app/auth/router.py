"""Auth API routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.settings import UserSettings
from ..schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from .service import hash_password, verify_password, create_access_token
from .dependencies import get_current_user

logger = logging.getLogger("ai_helper.auth")

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    data.email = data.email.strip().lower()
    logger.info(f"Registration attempt: {data.email}")

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        logger.warning(f"Registration failed: email already exists: {data.email}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Check if this is the first user (make them admin)
    result = await db.execute(select(User.id).limit(1))
    is_first_user = result.scalar_one_or_none() is None

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        role="admin" if is_first_user else "user",
    )
    db.add(user)
    await db.flush()

    # Create default settings
    settings = UserSettings(user_id=user.id)
    db.add(settings)

    token = create_access_token(user.id, user.role)
    logger.info(f"User registered: {data.email} (id={user.id}, role={user.role})")
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with email and password."""
    data.email = data.email.strip().lower()
    logger.info(f"Login attempt: {data.email}")

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        logger.warning(f"Login failed: user not found: {data.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(data.password, user.password_hash):
        logger.warning(f"Login failed: wrong password for: {data.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        logger.warning(f"Login failed: account deactivated: {data.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    token = create_access_token(user.id, user.role)
    logger.info(f"Login success: {data.email} (id={user.id}, role={user.role})")
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Get current user profile."""
    logger.debug(f"Get me: user_id={user.id}")
    return user
