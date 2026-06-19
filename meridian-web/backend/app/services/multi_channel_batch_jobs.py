"""In-memory реестр batch multi-channel STT jobs (Этап 9.5).

# Diagnostic in-memory job registry assumes the same process that owns MeetingRoom.
# Persistent/distributed jobs are intentionally deferred.

Ничего не пишется в БД/диск/S3. Result хранится только в памяти с TTL. Raw provider
response не хранится. WAV/snapshot держатся локально в runner и освобождаются в finally.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from .multi_channel_batch_stt import (
    BatchJobStatus,
    MultiChannelBatchResult,
    MultiChannelBatchSttError,
)

logger = logging.getLogger("meridian.batch_stt")

_NON_TERMINAL = {"queued", "preparing", "transcribing", "parsing", "comparing"}


class ActiveJobExistsError(RuntimeError):
    """У встречи/пользователя уже есть активный job (API → 409)."""


@dataclass
class MultiChannelBatchJob:
    job_id: str
    meeting_id: int
    owner_user_id: int
    status: BatchJobStatus
    stage: str
    progress: float
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = None
    provider: str = ""
    model: str = ""
    language: str = ""
    result: MultiChannelBatchResult | None = None
    comparison: dict | None = None
    export_manifest: dict | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False


# runner: async callable, получает job (обновляет stage/progress, кладёт result/comparison/manifest)
JobRunner = Callable[[MultiChannelBatchJob], Awaitable[None]]


class MultiChannelBatchJobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, MultiChannelBatchJob] = {}
        self._active: dict[tuple[int, int], str] = {}   # (meeting_id, user_id) -> job_id
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._sem: asyncio.Semaphore | None = None
        self._sem_size: int | None = None

    def _semaphore(self, size: int) -> asyncio.Semaphore:
        size = max(1, size)
        if self._sem is None or self._sem_size != size:
            self._sem = asyncio.Semaphore(size)
            self._sem_size = size
        return self._sem

    async def create_job(self, *, meeting_id: int, user_id: int, provider: str, model: str,
                         language: str, ttl_seconds: int, max_global_jobs: int,
                         runner: JobRunner) -> MultiChannelBatchJob:
        async with self._lock:
            key = (meeting_id, user_id)
            existing = self._active.get(key)
            if existing and existing in self._jobs and self._jobs[existing].status in _NON_TERMINAL:
                raise ActiveJobExistsError("Активный job уже выполняется для этой встречи")
            job = MultiChannelBatchJob(
                job_id=uuid.uuid4().hex, meeting_id=meeting_id, owner_user_id=user_id,
                status="queued", stage="queued", progress=0.0, created_at=datetime.utcnow(),
                provider=provider, model=model, language=language,
            )
            self._jobs[job.job_id] = job
            self._active[key] = job.job_id
            task = asyncio.create_task(self._run(job, runner, ttl_seconds, max_global_jobs))
            self._tasks[job.job_id] = task
        return job

    async def _run(self, job: MultiChannelBatchJob, runner: JobRunner,
                   ttl_seconds: int, max_global_jobs: int) -> None:
        sem = self._semaphore(max_global_jobs)
        try:
            async with sem:
                job.started_at = datetime.utcnow()
                job.status = "preparing"
                job.stage = "preparing"
                job.progress = 0.1
                await runner(job)
                job.status = "succeeded"
                job.stage = "succeeded"
                job.progress = 1.0
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.stage = "cancelled"
            job.error_code = "CANCELLED"
            job.result = None
            job.comparison = None
            # намеренно не пробрасываем: статус cancelled — это «успешное» завершение задачи
        except MultiChannelBatchSttError as e:
            job.status = "failed"
            job.stage = "failed"
            job.error_code = e.code
            job.error_message = str(e)
            job.retryable = e.retryable
        except Exception:  # noqa: BLE001 — не раскрываем детали наружу
            logger.warning("[batch-stt] job %s internal error", job.job_id, exc_info=False)
            job.status = "failed"
            job.stage = "failed"
            job.error_code = "INTERNAL_ERROR"
            job.error_message = "Внутренняя ошибка обработки"
            job.retryable = False
        finally:
            job.finished_at = datetime.utcnow()
            job.expires_at = job.finished_at + timedelta(seconds=ttl_seconds)
            self._active.pop((job.meeting_id, job.owner_user_id), None)
            self._tasks.pop(job.job_id, None)

    def _maybe_expire(self, job: MultiChannelBatchJob) -> None:
        if job.expires_at and datetime.utcnow() > job.expires_at and job.status != "expired":
            job.status = "expired"
            job.result = None
            job.comparison = None
            job.export_manifest = None

    async def get_job(self, job_id: str) -> MultiChannelBatchJob | None:
        job = self._jobs.get(job_id)
        if job is not None:
            self._maybe_expire(job)
        return job

    async def cancel_job(self, job_id: str) -> bool:
        """Отменить активный job и/или удалить завершённый из реестра."""
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        async with self._lock:
            job = self._jobs.pop(job_id, None)
            self._tasks.pop(job_id, None)
            if job is not None:
                key = (job.meeting_id, job.owner_user_id)
                if self._active.get(key) == job_id:
                    self._active.pop(key, None)
        return job is not None

    async def cancel_meeting_jobs(self, meeting_id: int) -> int:
        ids = [jid for jid, j in self._jobs.items()
               if j.meeting_id == meeting_id and j.status in _NON_TERMINAL]
        for jid in ids:
            await self.cancel_job(jid)
        return len(ids)

    async def cleanup_expired(self) -> int:
        now = datetime.utcnow()
        expired = [jid for jid, j in self._jobs.items()
                   if j.expires_at and now > j.expires_at]
        for jid in expired:
            self._jobs.pop(jid, None)
            self._tasks.pop(jid, None)
        return len(expired)


batch_job_registry = MultiChannelBatchJobRegistry()
