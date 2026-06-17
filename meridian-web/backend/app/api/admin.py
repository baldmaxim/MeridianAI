"""Admin API routes: manage users and API keys."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.api_key import ApiKey
from ..models.job import Job
from ..models.audit import AuditLog
from ..schemas.auth import UserResponse, AdminUserUpdate
from ..schemas.settings import ApiKeyCreate, ApiKeyResponse, ApiKeyUpdate
from ..auth.dependencies import require_admin
from ..auth.service import hash_password
from ..services.encryption import encrypt_api_key, decrypt_api_key, mask_api_key
from ..services.jobs import retry_dead
from ..services.audit import audit, client_ip, hmac_email

router = APIRouter()


# --- Users ---


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).order_by(User.department.asc().nulls_last(), User.created_at.desc())
    )
    return result.scalars().all()


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    request: Request,
    user_id: int,
    data: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    is_self = user_id == admin.id
    ip = client_ip(request)

    if data.display_name is not None and data.display_name != user.display_name:
        new_name = data.display_name.strip() or None
        await audit("user_name_changed", actor_user_id=admin.id, ip=ip,
                    target_user_id=user_id)
        user.display_name = new_name

    if data.role is not None and data.role != user.role:
        if data.role not in {"admin", "user"}:
            raise HTTPException(status_code=400, detail="Invalid role")
        if is_self and data.role != "admin":
            raise HTTPException(status_code=400, detail="Нельзя снять роль admin с самого себя")
        await audit("user_role_changed", actor_user_id=admin.id, ip=ip,
                    target_user_id=user_id, old=user.role, new=data.role)
        user.role = data.role

    if data.is_active is not None and data.is_active != user.is_active:
        if is_self and not data.is_active:
            raise HTTPException(status_code=400, detail="Нельзя деактивировать самого себя")
        await audit("user_active_changed", actor_user_id=admin.id, ip=ip,
                    target_user_id=user_id, new=data.is_active)
        user.is_active = data.is_active

    if data.password is not None:
        if not data.password.strip():
            raise HTTPException(status_code=400, detail="Пароль не может быть пустым")
        await audit("user_password_reset", actor_user_id=admin.id, ip=ip,
                    target_user_id=user_id)
        user.password_hash = hash_password(data.password)

    return user


@router.delete("/users/{user_id}")
async def delete_user(
    request: Request,
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить самого себя")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await audit("user_deleted", actor_user_id=admin.id, ip=client_ip(request),
                target_user_id=user_id, email_hmac=hmac_email(user.email))
    await db.delete(user)
    return {"ok": True}


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
    request: Request,
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
    await audit("api_key_created", actor_user_id=admin.id, ip=client_ip(request), service=data.service)

    return ApiKeyResponse(
        id=key.id,
        service=key.service,
        key_masked=mask_api_key(data.api_key),
        is_active=key.is_active,
    )


@router.put("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    request: Request,
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
    await audit("api_key_updated", actor_user_id=admin.id, ip=client_ip(request),
                service=key.service, key_id=key_id)

    try:
        plain = decrypt_api_key(key.encrypted_key)
        masked = mask_api_key(plain)
    except Exception:
        masked = "****"

    return ApiKeyResponse(id=key.id, service=key.service, key_masked=masked, is_active=key.is_active)


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    request: Request,
    key_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    await audit("api_key_deleted", actor_user_id=admin.id, ip=client_ip(request),
                service=key.service, key_id=key_id)
    await db.delete(key)
    return {"ok": True}


# --- Jobs (§16) ---


@router.get("/jobs")
async def list_jobs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(Job).order_by(Job.created_at.desc()).limit(100))
    ).scalars().all()
    return [
        {
            "id": j.id,
            "type": j.type,
            "status": j.status,
            "attempts": j.attempts,
            "max_attempts": j.max_attempts,
            "last_error": j.last_error,
            "next_run_at": j.next_run_at,
            "created_at": j.created_at,
        }
        for j in rows
    ]


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    job = await retry_dead(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "status": job.status}


# --- Audit (§22) ---


@router.get("/audit")
async def list_audit(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(AuditLog).order_by(AuditLog.ts.desc()).limit(200))
    ).scalars().all()
    return [
        {
            "id": a.id,
            "ts": a.ts,
            "actor_user_id": a.actor_user_id,
            "event_type": a.event_type,
            "ip": a.ip,
            "details": a.details,
        }
        for a in rows
    ]
