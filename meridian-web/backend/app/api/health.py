"""Healthcheck / diagnostics (Этап 10). Без секретов в ответах.

- GET /api/health          — публичный лёгкий статус (db ping + флаги конфигурации).
- GET /api/health/jobs     — сводка очереди задач.
- GET /api/health/config-summary — безопасные флаги конфигурации.
- GET /api/health/deep     — admin/dev: db/alembic/S3/jobs (без секретов, без дорогих LLM-вызовов).
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db, engine
from ..models.user import User
from ..models.api_key import ApiKey
from ..auth.dependencies import get_current_user
from ..services.jobs import job_counts, recover_stale_jobs
from ..services import s3

logger = logging.getLogger("meridian.health")

router = APIRouter()

_STT_SERVICES = {"deepgram", "elevenlabs", "speechmatics"}


async def _active_services(db: AsyncSession) -> set[str]:
    rows = (await db.execute(select(ApiKey.service).where(ApiKey.is_active == True))).scalars().all()  # noqa: E712
    return set(rows)


async def _db_ok() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("health db check failed: %s", e)
        return False


@router.get("")
async def health(db: AsyncSession = Depends(get_db)):
    """Публичный статус — без секретов."""
    s = get_settings()
    db_ok = await _db_ok()
    try:
        services = await _active_services(db)
    except Exception:
        services = set()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": s.app_version,
        "time": datetime.utcnow().isoformat() + "Z",
        "environment": s.environment,
        "database": "ok" if db_ok else "error",
        "worker_hint": "запускайте отдельный процесс: python -m app.worker",
        "s3_configured": s.s3_enabled,
        "llm_configured": "openrouter" in services,
        "stt_configured": bool(services & _STT_SERVICES),
    }


@router.get("/config-summary")
async def config_summary(user: User = Depends(get_current_user)):
    """Безопасные флаги конфигурации (любой авторизованный). Без секретов."""
    return get_settings().safe_config_summary()


@router.get("/jobs")
async def jobs_health(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Сводка очереди фоновых задач."""
    return await job_counts(db)


def _require_admin_or_dev(user: User) -> None:
    if user.role != "admin" and not get_settings().dev_mode:
        raise HTTPException(403, "Только для администратора")


@router.get("/deep")
async def deep_health(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Расширенная диагностика (admin/dev). Без секретов, без дорогих LLM-вызовов."""
    _require_admin_or_dev(user)
    s = get_settings()

    db_ok = await _db_ok()

    # alembic current / head
    alembic = {"current": None, "head": None}
    try:
        cur = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        alembic["current"] = cur
    except Exception:
        alembic["current"] = "unknown"
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        import os
        ini = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "alembic.ini")
        heads = ScriptDirectory.from_config(Config(ini)).get_heads()
        alembic["head"] = heads[0] if len(heads) == 1 else list(heads)
        alembic["single_head"] = len(heads) == 1
    except Exception as e:
        alembic["head"] = "unknown"
        logger.warning("alembic head detect failed: %s", e)

    # S3
    if s.s3_enabled:
        ok, detail = await s3.ping()
        s3_status = {"configured": True, "reachable": ok, "detail": detail}
    else:
        s3_status = {"configured": False, "reachable": False, "detail": "not configured"}

    services = await _active_services(db)
    jobs = await job_counts(db)

    return {
        "status": "ok" if db_ok else "degraded",
        "version": s.app_version,
        "time": datetime.utcnow().isoformat() + "Z",
        "database": "ok" if db_ok else "error",
        "alembic": alembic,
        "s3": s3_status,
        "jobs": jobs,
        "llm_configured": "openrouter" in services,
        "stt_configured": bool(services & _STT_SERVICES),
        "config": s.safe_config_summary(),
    }


@router.post("/jobs/recover-stale")
async def recover_stale(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Вернуть зависшие running-задачи в очередь (admin/dev)."""
    _require_admin_or_dev(user)
    result = await recover_stale_jobs(db)
    logger.info("manual stale-recovery by user %s: %s", user.id, result)
    return result
