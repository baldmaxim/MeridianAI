"""Тесты in-memory batch STT job registry (Этап 9.5)."""

import asyncio

import pytest

from app.services.multi_channel_batch_jobs import (
    ActiveJobExistsError,
    MultiChannelBatchJobRegistry,
)
from app.services.multi_channel_batch_stt import MultiChannelBatchSttError


async def _wait(job, *, timeout=2.0):
    terminal = {"succeeded", "failed", "cancelled", "expired"}
    waited = 0.0
    while job.status not in terminal and waited < timeout:
        await asyncio.sleep(0.01)
        waited += 0.01
    return job


def reg():
    return MultiChannelBatchJobRegistry()


async def test_job_success_sets_result_and_progress():
    r = reg()

    async def runner(job):
        job.result = "RESULT"
        job.comparison = {"available": True}

    job = await r.create_job(meeting_id=1, user_id=1, provider="deepgram", model="m",
                             language="ru", ttl_seconds=900, max_global_jobs=2, runner=runner)
    await _wait(job)
    assert job.status == "succeeded"
    assert job.progress == 1.0
    assert job.result == "RESULT"
    assert job.expires_at is not None


async def test_job_failure_maps_error():
    r = reg()

    async def runner(job):
        raise MultiChannelBatchSttError("PROVIDER_TIMEOUT", "timeout", retryable=True)

    job = await r.create_job(meeting_id=1, user_id=1, provider="deepgram", model="m",
                             language="ru", ttl_seconds=900, max_global_jobs=2, runner=runner)
    await _wait(job)
    assert job.status == "failed"
    assert job.error_code == "PROVIDER_TIMEOUT"
    assert job.retryable is True


async def test_job_internal_error_not_leaked():
    r = reg()

    async def runner(job):
        raise RuntimeError("secret internal detail")

    job = await r.create_job(meeting_id=1, user_id=1, provider="deepgram", model="m",
                             language="ru", ttl_seconds=900, max_global_jobs=2, runner=runner)
    await _wait(job)
    assert job.status == "failed"
    assert job.error_code == "INTERNAL_ERROR"
    assert "secret internal detail" not in (job.error_message or "")


async def test_duplicate_active_job_rejected():
    r = reg()
    gate = asyncio.Event()

    async def runner(job):
        await gate.wait()

    job1 = await r.create_job(meeting_id=1, user_id=1, provider="d", model="m",
                              language="ru", ttl_seconds=900, max_global_jobs=2, runner=runner)
    await asyncio.sleep(0.02)
    with pytest.raises(ActiveJobExistsError):
        await r.create_job(meeting_id=1, user_id=1, provider="d", model="m",
                           language="ru", ttl_seconds=900, max_global_jobs=2, runner=runner)
    gate.set()
    await _wait(job1)
    assert job1.status == "succeeded"


async def test_cancel_running_job():
    r = reg()
    started = asyncio.Event()

    async def runner(job):
        started.set()
        await asyncio.sleep(10)

    job = await r.create_job(meeting_id=2, user_id=1, provider="d", model="m",
                             language="ru", ttl_seconds=900, max_global_jobs=2, runner=runner)
    await started.wait()
    ok = await r.cancel_job(job.job_id)
    assert ok is True
    assert job.status == "cancelled"
    assert await r.get_job(job.job_id) is None        # удалён из реестра


async def test_global_semaphore_serializes():
    r = reg()
    gate = asyncio.Event()

    async def runner(job):
        await gate.wait()

    j1 = await r.create_job(meeting_id=1, user_id=1, provider="d", model="m",
                            language="ru", ttl_seconds=900, max_global_jobs=1, runner=runner)
    await asyncio.sleep(0.02)
    j2 = await r.create_job(meeting_id=2, user_id=2, provider="d", model="m",
                            language="ru", ttl_seconds=900, max_global_jobs=1, runner=runner)
    await asyncio.sleep(0.02)
    # семафор=1: первый «preparing», второй ждёт слот → «queued»
    assert j1.status == "preparing"
    assert j2.status == "queued"
    gate.set()
    await _wait(j1)
    await _wait(j2)
    assert j1.status == "succeeded" and j2.status == "succeeded"


async def test_ttl_expiry_clears_result():
    r = reg()

    async def runner(job):
        job.result = "BIG"
        job.comparison = {"available": True}
        job.export_manifest = {"channels": 2}

    job = await r.create_job(meeting_id=1, user_id=1, provider="d", model="m",
                             language="ru", ttl_seconds=0, max_global_jobs=2, runner=runner)
    await _wait(job)
    await asyncio.sleep(0.02)
    refreshed = await r.get_job(job.job_id)
    assert refreshed.status == "expired"
    assert refreshed.result is None                    # крупные ссылки освобождены
    assert refreshed.comparison is None
    assert refreshed.export_manifest is None


async def test_cleanup_expired_removes_jobs():
    r = reg()

    async def runner(job):
        job.result = "x"

    job = await r.create_job(meeting_id=1, user_id=1, provider="d", model="m",
                             language="ru", ttl_seconds=0, max_global_jobs=2, runner=runner)
    await _wait(job)
    await asyncio.sleep(0.02)
    removed = await r.cleanup_expired()
    assert removed >= 1
    assert await r.get_job(job.job_id) is None


async def test_job_runs_only_once():
    r = reg()
    calls = {"n": 0}

    async def runner(job):
        calls["n"] += 1

    job = await r.create_job(meeting_id=1, user_id=1, provider="d", model="m",
                             language="ru", ttl_seconds=900, max_global_jobs=2, runner=runner)
    await _wait(job)
    await asyncio.sleep(0.02)
    assert calls["n"] == 1
