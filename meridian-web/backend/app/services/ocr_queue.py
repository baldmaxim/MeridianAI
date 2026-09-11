# -*- coding: utf-8 -*-
"""Очередь распознавания сканов для агента на компьютере пользователя.

Модель chandra-ocr-2 работает в LM Studio на домашнем компьютере за NAT: сервер до неё не
достучится. Как в MailHub, направление обращено — документ ставится в очередь, агент сам
забирает задачу по HTTPS, скачивает PDF по короткой ссылке, распознаёт страницы локально
и сдаёт текст постранично. Когда все страницы сданы, документ уходит в обычную обработку:
чанкинг и поиск не знают, откуда взялся текст.

Все функции коммит оставляют вызывающему.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.document import DocumentRecord
from ..models.ocr import DocumentOcrPage, DocumentOcrTask, OcrAgent
from .jobs import enqueue

logger = logging.getLogger("meridian.ocr_queue")

# Статус документа, пока скан ждёт агента. Опрос статуса в интерфейсе на нём не крутится:
# компьютер может быть выключен часами.
AWAITING_OCR = "awaiting_ocr"

MAX_PAGE_TEXT_CHARS = 200_000
MAX_ERROR_CHARS = 1000


class OcrQueueError(ValueError):
    """Агент прислал то, что принять нельзя (сообщение уходит агенту)."""


def _now() -> datetime:
    return datetime.utcnow()


# ── токены агентов ────────────────────────────────────────────────────────


def hash_token(token: str) -> str:
    """sha256 токена. Токен — 256 бит случайности: подобрать по хэшу нельзя, а искать по
    индексу можно, без перебора всех агентов (в отличие от солёного argon2)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def enroll_agent(db: AsyncSession, name: str, user_id: int | None) -> tuple[OcrAgent, str]:
    """Завести агента. Токен показывается один раз: в базе только его хэш."""
    token = secrets.token_urlsafe(32)
    agent = OcrAgent(name=(name or "").strip()[:120] or "Компьютер с LM Studio",
                     token_hash=hash_token(token), created_by_user_id=user_id)
    db.add(agent)
    await db.flush()
    logger.info("заведён OCR-агент %s", agent.id)
    return agent, token


async def authenticate_agent(db: AsyncSession, token: str | None) -> OcrAgent | None:
    if not token:
        return None
    agent = (await db.execute(
        select(OcrAgent).where(OcrAgent.token_hash == hash_token(token), OcrAgent.revoked_at.is_(None))
    )).scalar_one_or_none()
    if agent is not None:
        agent.last_seen_at = _now()
    return agent


def note_agent(agent: OcrAgent, model: str | None, version: str | None) -> None:
    """Запомнить, какая модель и версия агента сейчас работают — для админки."""
    if model:
        agent.model = str(model)[:200]
    if version:
        agent.agent_version = str(version)[:40]


async def revoke_agent(db: AsyncSession, agent_id: int) -> bool:
    agent = await db.get(OcrAgent, agent_id)
    if agent is None or agent.revoked_at is not None:
        return False
    agent.revoked_at = _now()
    # Задачи отозванного агента освобождаются сразу, а не по истечении аренды.
    tasks = (await db.execute(
        select(DocumentOcrTask).where(DocumentOcrTask.agent_id == agent_id,
                                      DocumentOcrTask.status == "leased")
    )).scalars().all()
    for task in tasks:
        task.status, task.lease_until, task.agent_id = "pending", None, None
    return True


# ── постановка в очередь ──────────────────────────────────────────────────


async def request_ocr(db: AsyncSession, document: DocumentRecord) -> DocumentOcrTask:
    """Поставить документ на распознавание (или заново — со сбросом сданных страниц)."""
    task = (await db.execute(
        select(DocumentOcrTask).where(DocumentOcrTask.document_id == document.id)
    )).scalar_one_or_none()
    if task is None:
        task = DocumentOcrTask(document_id=document.id, status="pending", attempts=0)
        db.add(task)
        await db.flush()
    else:
        await db.execute(delete(DocumentOcrPage).where(DocumentOcrPage.task_id == task.id))
        task.status, task.attempts, task.lease_until, task.agent_id = "pending", 0, None, None
        task.pages_total, task.last_error, task.completed_at = None, None, None
    document.status = AWAITING_OCR
    document.processing_error = None
    logger.info("document %s: поставлен в очередь распознавания", document.id)
    return task


async def ocr_segments(db: AsyncSession, document_id: int) -> tuple[list[dict], int] | None:
    """Готовый распознанный текст документа по страницам или None, если его ещё нет."""
    task = (await db.execute(
        select(DocumentOcrTask).where(DocumentOcrTask.document_id == document_id,
                                      DocumentOcrTask.status == "done")
    )).scalar_one_or_none()
    if task is None:
        return None
    pages = (await db.execute(
        select(DocumentOcrPage).where(DocumentOcrPage.task_id == task.id)
        .order_by(DocumentOcrPage.page_number)
    )).scalars().all()
    segments = [{"text": p.text, "page_number": p.page_number, "sheet_name": None}
                for p in pages if (p.text or "").strip()]
    return segments, task.pages_total or len(pages)


# ── работа агента ─────────────────────────────────────────────────────────


async def _fail_exhausted(db: AsyncSession, now: datetime) -> None:
    """Задачи, у которых кончились попытки, а аренда истекла, — в failed с объяснением."""
    settings = get_settings()
    stuck = (await db.execute(
        select(DocumentOcrTask).where(
            DocumentOcrTask.status == "leased",
            DocumentOcrTask.lease_until < now,
            DocumentOcrTask.attempts >= settings.ocr_agent_max_attempts,
        )
    )).scalars().all()
    for task in stuck:
        await _mark_failed(db, task, f"агент {task.attempts} раз не довёл распознавание до конца "
                                     f"(компьютер выключался или LM Studio не отвечал)")


async def _mark_failed(db: AsyncSession, task: DocumentOcrTask, reason: str) -> None:
    task.status, task.lease_until, task.agent_id = "failed", None, None
    task.last_error = reason[:MAX_ERROR_CHARS]
    doc = await db.get(DocumentRecord, task.document_id)
    if doc is not None:
        doc.status = "error"
        doc.processing_error = f"Распознавание скана не удалось: {reason}"[:500]
    logger.warning("document %s: распознавание не удалось", task.document_id)


async def claim_task(db: AsyncSession, agent: OcrAgent, *, pdf_url_for) -> dict | None:
    """Выдать агенту одну задачу в аренду.

    pdf_url_for(s3_key) → короткая ссылка на скачивание PDF (подставляется снаружи, чтобы
    очередь не зависела от хранилища и тестировалась без S3).
    """
    settings = get_settings()
    now = _now()
    await _fail_exhausted(db, now)

    task = (await db.execute(
        select(DocumentOcrTask).where(
            or_(DocumentOcrTask.status == "pending",
                and_(DocumentOcrTask.status == "leased", DocumentOcrTask.lease_until < now)),
            DocumentOcrTask.attempts < settings.ocr_agent_max_attempts,
        )
        .order_by(DocumentOcrTask.created_at, DocumentOcrTask.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )).scalar_one_or_none()
    if task is None:
        return None

    doc = await db.get(DocumentRecord, task.document_id)
    if doc is None or not doc.s3_key:
        await _mark_failed(db, task, "исходный файл документа недоступен")
        return None

    task.status = "leased"
    task.attempts += 1
    task.agent_id = agent.id
    task.lease_until = now + timedelta(seconds=settings.ocr_agent_lease_seconds)
    done = (await db.execute(
        select(DocumentOcrPage.page_number).where(DocumentOcrPage.task_id == task.id)
    )).scalars().all()
    await db.flush()
    logger.info("OCR-задача %s (документ %s) выдана агенту %s, попытка %s",
                task.id, doc.id, agent.id, task.attempts)
    return {
        "task_id": task.id,
        "document_id": doc.id,
        "file_name": doc.original_name,
        "pdf_url": pdf_url_for(doc.s3_key),
        "lease_seconds": settings.ocr_agent_lease_seconds,
        "max_pages": settings.document_ocr_max_pages,
        "pages_done": sorted(done),
    }


async def _leased_by(db: AsyncSession, agent: OcrAgent, task_id: int) -> DocumentOcrTask:
    task = await db.get(DocumentOcrTask, task_id)
    if task is None or task.status != "leased" or task.agent_id != agent.id:
        # Аренда могла уйти другому агенту, пока этот компьютер спал.
        raise OcrQueueError("задача не арендована этим агентом")
    return task


async def submit_page(db: AsyncSession, agent: OcrAgent, task_id: int, *,
                      page_number: int, pages_total: int, text: str,
                      model: str | None = None) -> int:
    """Принять одну распознанную страницу. Продлевает аренду. Возвращает число сданных страниц."""
    settings = get_settings()
    task = await _leased_by(db, agent, task_id)
    if not 1 <= pages_total <= settings.document_ocr_max_pages:
        raise OcrQueueError(f"страниц {pages_total} — вне лимита 1..{settings.document_ocr_max_pages}")
    if not 1 <= page_number <= pages_total:
        raise OcrQueueError(f"номер страницы {page_number} вне 1..{pages_total}")
    text = text or ""
    if len(text) > MAX_PAGE_TEXT_CHARS:
        raise OcrQueueError("текст страницы слишком длинный")

    page = (await db.execute(
        select(DocumentOcrPage).where(DocumentOcrPage.task_id == task.id,
                                      DocumentOcrPage.page_number == page_number)
    )).scalar_one_or_none()
    if page is None:
        db.add(DocumentOcrPage(task_id=task.id, page_number=page_number, text=text))
    else:
        page.text = text

    task.pages_total = pages_total
    if model:
        task.model = str(model)[:200]
    task.lease_until = _now() + timedelta(seconds=settings.ocr_agent_lease_seconds)
    await db.flush()
    return (await db.execute(
        select(func.count()).select_from(DocumentOcrPage).where(DocumentOcrPage.task_id == task.id)
    )).scalar_one()


async def complete_task(db: AsyncSession, agent: OcrAgent, task_id: int) -> None:
    """Все страницы сданы — документ уходит в обычную обработку."""
    task = await _leased_by(db, agent, task_id)
    done = (await db.execute(
        select(func.count()).select_from(DocumentOcrPage).where(DocumentOcrPage.task_id == task.id)
    )).scalar_one()
    if not task.pages_total or done < task.pages_total:
        # Частичный текст опаснее отсутствующего: подсказка не заметит пропавших пунктов.
        raise OcrQueueError(f"сдано {done} из {task.pages_total or '?'} страниц")

    task.status, task.lease_until, task.completed_at = "done", None, _now()
    doc = await db.get(DocumentRecord, task.document_id)
    if doc is not None:
        doc.status = "uploaded"
        doc.processing_error = None
        await enqueue(db, "document_process", {"document_id": doc.id})
    logger.info("OCR-задача %s завершена: %s стр.", task.id, done)


async def fail_task(db: AsyncSession, agent: OcrAgent, task_id: int, error: str) -> None:
    """Агент не смог распознать. Повтор до лимита попыток, потом документ — в ошибку."""
    settings = get_settings()
    task = await _leased_by(db, agent, task_id)
    reason = (error or "без описания").strip()[:MAX_ERROR_CHARS]
    if task.attempts >= settings.ocr_agent_max_attempts:
        await _mark_failed(db, task, reason)
        return
    task.status, task.lease_until, task.agent_id = "pending", None, None
    task.last_error = reason


# ── состояние для админки ─────────────────────────────────────────────────


async def queue_status(db: AsyncSession) -> dict:
    settings = get_settings()
    now = _now()
    counts = dict((await db.execute(
        select(DocumentOcrTask.status, func.count()).group_by(DocumentOcrTask.status)
    )).all())
    agents = (await db.execute(
        select(OcrAgent).where(OcrAgent.revoked_at.is_(None)).order_by(OcrAgent.id)
    )).scalars().all()
    online_after = now - timedelta(seconds=settings.ocr_agent_online_seconds)
    return {
        "pending": counts.get("pending", 0),
        "leased": counts.get("leased", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "agents": [{
            "id": a.id, "name": a.name, "model": a.model, "agent_version": a.agent_version,
            "created_at": a.created_at, "last_seen_at": a.last_seen_at,
            "online": bool(a.last_seen_at and a.last_seen_at >= online_after),
        } for a in agents],
    }
