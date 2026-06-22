"""Отдельный процесс-воркер фоновых задач (§16).

Запуск: python -m app.worker
Поллит таблицу jobs, атомарно захватывает задачи, диспетчеризует по type,
ретраит с backoff, graceful-останов по SIGTERM/SIGINT.
"""

import asyncio
import logging
import os
import signal
import socket
import time

from .config import get_settings
from .database import async_session, engine
from .logging_setup import setup_logging
from .services.jobs import claim_one, complete, fail, recover_stale_jobs
from .core.batch.processor import handle_batch_transcribe
from .core.batch.meeting_audio_archive import handle_meeting_audio_archive
from .services.files import handle_file_physical_delete
from .services.document_processing import handle_document_process
from .services.meeting_finalize import handle_meeting_finalize
from .services.learning_extract import handle_learning_extract

settings = get_settings()
setup_logging(dev_mode=settings.dev_mode)
logger = logging.getLogger("meridian.worker")

HANDLERS = {
    "batch_transcribe": handle_batch_transcribe,
    "meeting_audio_archive": handle_meeting_audio_archive,
    "file_physical_delete": handle_file_physical_delete,
    "document_process": handle_document_process,
    "meeting_finalize": handle_meeting_finalize,
    "learning_extract": handle_learning_extract,
}

IDLE_SLEEP = settings.worker_poll_interval_seconds


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def run() -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows
    logger.info("worker %s started", worker_id)

    # §16: при старте вернуть в очередь задачи, зависшие после падения воркера
    try:
        async with async_session() as db:
            rec = await recover_stale_jobs(db)
        if rec["scanned"]:
            logger.info("worker startup recovery: %s", rec)
    except Exception:
        logger.exception("worker startup stale-recovery failed")

    while not stop.is_set():
        try:
            async with async_session() as db:
                claimed = await claim_one(db, worker_id)
            if not claimed:
                await _sleep_or_stop(stop, IDLE_SLEEP)
                continue

            jid, jtype = claimed["id"], claimed["type"]
            handler = HANDLERS.get(jtype)
            if handler is None:
                async with async_session() as db:
                    await fail(db, jid, f"нет обработчика для type={jtype}")
                logger.warning("job %s (%s) no handler -> failed", jid, jtype)
                continue

            logger.info("job %s (%s) attempt %s started", jid, jtype, claimed["attempts"])
            t0 = time.monotonic()
            try:
                await handler(claimed["payload"])
                async with async_session() as db:
                    await complete(db, jid)
                logger.info("job %s (%s) done in %dms", jid, jtype, int((time.monotonic() - t0) * 1000))
            except Exception as e:
                # одна плохая задача не валит воркер: фиксируем fail (retry/dead) и продолжаем
                logger.exception("job %s (%s) failed in %dms", jid, jtype, int((time.monotonic() - t0) * 1000))
                async with async_session() as db:
                    await fail(db, jid, str(e))
        except Exception:
            logger.exception("worker loop error")
            await _sleep_or_stop(stop, 5)

    await engine.dispose()
    logger.info("worker %s stopped", worker_id)


if __name__ == "__main__":
    asyncio.run(run())
