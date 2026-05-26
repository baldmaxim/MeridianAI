"""Admin API routes: manage users and API keys."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.api_key import ApiKey
from ..schemas.auth import UserResponse
from ..schemas.settings import ApiKeyCreate, ApiKeyResponse, ApiKeyUpdate
from ..auth.dependencies import require_admin
from ..services.encryption import encrypt_api_key, decrypt_api_key, mask_api_key

router = APIRouter()


# --- Users ---


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    is_active: bool | None = None,
    role: str | None = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if is_active is not None:
        user.is_active = is_active
    if role is not None:
        user.role = role
    return user


# --- API Keys ---


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiKey).order_by(ApiKey.service))
    keys = result.scalars().all()
    response = []
    for k in keys:
        try:
            plain = decrypt_api_key(k.encrypted_key)
            masked = mask_api_key(plain)
        except Exception:
            masked = "****[decrypt error]"
        response.append(
            ApiKeyResponse(id=k.id, service=k.service, key_masked=masked, is_active=k.is_active)
        )
    return response


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    valid_services = {"elevenlabs", "deepgram", "gemini", "openrouter", "speechmatics"}
    if data.service not in valid_services:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid service. Must be one of: {', '.join(valid_services)}",
        )

    key = ApiKey(
        service=data.service,
        encrypted_key=encrypt_api_key(data.api_key),
        created_by=admin.id,
    )
    db.add(key)
    await db.flush()

    return ApiKeyResponse(
        id=key.id,
        service=key.service,
        key_masked=mask_api_key(data.api_key),
        is_active=key.is_active,
    )


@router.put("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: int,
    data: ApiKeyUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    if data.api_key is not None:
        key.encrypted_key = encrypt_api_key(data.api_key)
    if data.is_active is not None:
        key.is_active = data.is_active

    try:
        plain = decrypt_api_key(key.encrypted_key)
        masked = mask_api_key(plain)
    except Exception:
        masked = "****"

    return ApiKeyResponse(id=key.id, service=key.service, key_masked=masked, is_active=key.is_active)


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.delete(key)
    return {"ok": True}
