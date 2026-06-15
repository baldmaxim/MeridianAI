"""PostgreSQL-based очередь задач (§16): enqueue (outbox), claim, retry, dead-state."""

import random
from datetime import datetime, timedelta

from sqlalchemy import select, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.job import Job

MAX_BACKOFF_SECONDS = 600


def _utcnow() -> datetime:
    return datetime.utcnow()


async def enqueue(db: AsyncSession, type: str, payload: dict, max_attempts: int | None = None) -> Job:
    """Поставить задачу. Коммитит ВЫЗЫВАЮЩИЙ — в одной транзакции с бизнес-записью (outbox)."""
    if max_attempts is None:
        max_attempts = get_settings().job_max_attempts
    job = Job(
        type=type,
        payload=payload,
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        next_run_at=_utcnow(),
    )
    db.add(job)
    await db.flush()
    return job


async def claim_one(db: AsyncSession, worker_id: str, lock_seconds: int = 600) -> dict | None:
    """Атомарно захватить одну готовую задачу через FOR UPDATE SKIP LOCKED.

    Берёт pending с наступившим next_run_at ИЛИ running с истёкшим locked_until
    (переподхват осиротевших после падения воркера). Возвращает простые значения
    (сессия закрывается у вызывающего), либо None.
    """
    now = _utcnow()
    stmt = (
        select(Job)
        .where(
            or_(
                and_(Job.status == "pending", Job.next_run_at <= now),
                and_(Job.status == "running", Job.locked_until < now),
            )
        )
        .order_by(Job.next_run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.locked_by = worker_id
    job.locked_until = now + timedelta(seconds=lock_seconds)
    job.attempts += 1
    await db.commit()
    return {"id": job.id, "type": job.type, "payload": job.payload, "attempts": job.attempts}


async def complete(db: AsyncSession, job_id: int) -> None:
    job = await db.get(Job, job_id)
    if job:
        job.status = "done"
        job.locked_by = None
        job.locked_until = None
        await db.commit()


async def fail(db: AsyncSession, job_id: int, error: str) -> None:
    """Зафиксировать ошибку: ретрай с exponential backoff + jitter, либо dead."""
    job = await db.get(Job, job_id)
    if job is None:
        return
    s = get_settings()
    job.last_error = (error or "")[: s.job_error_max_chars]
    job.locked_by = None
    job.locked_until = None
    went_dead = job.attempts >= job.max_attempts
    if went_dead:
        job.status = "dead"
    else:
        base = max(1, s.job_retry_base_seconds)
        backoff = min(MAX_BACKOFF_SECONDS, base * (2 ** (job.attempts - 1))) + random.uniform(0, 5)
        job.status = "pending"
        job.next_run_at = _utcnow() + timedelta(seconds=backoff)
    await db.commit()
    if went_dead:
        from .audit import audit
        await audit("job_dead", job_type=job.type, job_id=job.id, last_error=job.last_error)


async def recover_stale_jobs(db: AsyncSession, older_than_minutes: int | None = None) -> dict:
    """Вернуть «зависшие» running-задачи в очередь (или dead по лимиту попыток).

    Stale = running с истёкшим locked_until ЛИБО updated_at старше порога (воркер умер).
    """
    s = get_settings()
    minutes = older_than_minutes if older_than_minutes is not None else s.job_stale_running_minutes
    now = _utcnow()
    threshold = now - timedelta(minutes=minutes)
    rows = (await db.execute(
        select(Job).where(
            Job.status == "running",
            or_(Job.locked_until < now, Job.updated_at < threshold),
        )
    )).scalars().all()
    recovered = dead = 0
    for job in rows:
        job.locked_by = None
        job.locked_until = None
        if job.attempts >= job.max_attempts:
            job.status = "dead"
            dead += 1
        else:
            job.status = "pending"
            job.next_run_at = now
            recovered += 1
    if rows:
        await db.commit()
    return {"recovered": recovered, "dead": dead, "scanned": len(rows)}


async def job_counts(db: AsyncSession) -> dict:
    """Сводка очереди: по статусам/типам, самая старая queued, dead за 24ч."""
    by_status = {s: c for s, c in (await db.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status))).all()}
    by_type = {t: c for t, c in (await db.execute(
        select(Job.type, func.count(Job.id)).group_by(Job.type))).all()}
    oldest_queued = (await db.execute(
        select(func.min(Job.next_run_at)).where(Job.status == "pending"))).scalar()
    day_ago = _utcnow() - timedelta(hours=24)
    dead_24h = (await db.execute(
        select(func.count(Job.id)).where(Job.status == "dead", Job.updated_at >= day_ago))).scalar()
    return {
        "by_status": by_status,
        "by_type": by_type,
        "oldest_queued_at": oldest_queued.isoformat() if oldest_queued else None,
        "dead_last_24h": dead_24h or 0,
    }


async def retry_dead(db: AsyncSession, job_id: int) -> Job | None:
    """Админ-ретрай: вернуть задачу (обычно dead) в pending, сбросить счётчик."""
    job = await db.get(Job, job_id)
    if job is None:
        return None
    job.status = "pending"
    job.attempts = 0
    job.next_run_at = _utcnow()
    job.last_error = None
    job.locked_by = None
    job.locked_until = None
    await db.commit()
    return job
