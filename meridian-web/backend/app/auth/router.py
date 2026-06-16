"""Auth API routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.settings import UserSettings
from ..schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from ..ratelimit import limiter
from ..services.audit import audit, hmac_email, client_ip
from ..services.page_access import get_allowed_pages
from ..core.pages import PAGE_KEYS
from .service import hash_password, verify_password, create_access_token
from .dependencies import get_current_user

logger = logging.getLogger("meridian.auth")

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
@limiter.limit("5/minute")
async def register(request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    data.email = data.email.strip().lower()

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        await audit("register_conflict", ip=client_ip(request), email_hmac=hmac_email(data.email))
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
    await audit(
        "user_registered",
        actor_user_id=user.id,
        ip=client_ip(request),
        email_hmac=hmac_email(data.email),
        role=user.role,
    )
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with email and password."""
    data.email = data.email.strip().lower()
    ip = client_ip(request)
    email_hmac = hmac_email(data.email)

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        await audit("login_failed", ip=ip, email_hmac=email_hmac, reason="no_user")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(data.password, user.password_hash):
        await audit("login_failed", actor_user_id=user.id, ip=ip, email_hmac=email_hmac, reason="bad_password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        await audit("login_blocked", actor_user_id=user.id, ip=ip, email_hmac=email_hmac, reason="inactive")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    token = create_access_token(user.id, user.role)
    await audit("login_success", actor_user_id=user.id, ip=ip)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user profile + доступные страницы (page-access)."""
    logger.debug(f"Get me: user_id={user.id}")
    allowed = await get_allowed_pages(db, user.role)
    resp = UserResponse.model_validate(user)
    resp.allowed_pages = [k for k in PAGE_KEYS if k in allowed]
    if user.role == "admin":
        user_allowed = await get_allowed_pages(db, "user")
        resp.user_role_pages = [k for k in PAGE_KEYS if k in user_allowed]
    return resp
