"""PostgreSQL-based очередь задач (§16): enqueue (outbox), claim, retry, dead-state."""

import random
from datetime import datetime, timedelta

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.job import Job

MAX_BACKOFF_SECONDS = 600


def _utcnow() -> datetime:
    return datetime.utcnow()


async def enqueue(db: AsyncSession, type: str, payload: dict, max_attempts: int = 5) -> Job:
    """Поставить задачу. Коммитит ВЫЗЫВАЮЩИЙ — в одной транзакции с бизнес-записью (outbox)."""
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
    job.last_error = (error or "")[:1000]
    job.locked_by = None
    job.locked_until = None
    if job.attempts >= job.max_attempts:
        job.status = "dead"
    else:
        backoff = min(MAX_BACKOFF_SECONDS, 2 ** job.attempts) + random.uniform(0, 5)
        job.status = "pending"
        job.next_run_at = _utcnow() + timedelta(seconds=backoff)
    await db.commit()


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
