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

from .config import get_settings
from .database import async_session, engine
from .logging_setup import setup_logging
from .services.jobs import claim_one, complete, fail
from .core.batch.processor import handle_batch_transcribe
from .services.files import handle_file_physical_delete

settings = get_settings()
setup_logging(dev_mode=settings.dev_mode)
logger = logging.getLogger("meridian.worker")

HANDLERS = {
    "batch_transcribe": handle_batch_transcribe,
    "file_physical_delete": handle_file_physical_delete,
}

IDLE_SLEEP = 2


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
                continue

            logger.info("job %s (%s) attempt %s", jid, jtype, claimed["attempts"])
            try:
                await handler(claimed["payload"])
                async with async_session() as db:
                    await complete(db, jid)
                logger.info("job %s done", jid)
            except Exception as e:
                logger.exception("job %s failed", jid)
                async with async_session() as db:
                    await fail(db, jid, str(e))
        except Exception:
            logger.exception("worker loop error")
            await _sleep_or_stop(stop, 5)

    await engine.dispose()
    logger.info("worker %s stopped", worker_id)


if __name__ == "__main__":
    asyncio.run(run())
