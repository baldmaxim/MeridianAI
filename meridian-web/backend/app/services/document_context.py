"""DocumentContextService (Этап 4): подбор релевантных чанков документов встречи
для LLM-подсказок. MVP — лексический keyword-scoring по DocumentChunk.

Готово к будущему переходу на embeddings/vector search: интерфейс
get_relevant_chunks_for_meeting() стабилен, меняется только реализация scoring.
"""

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import async_session
from ..models.meeting import MeetingDocumentRecord
from ..models.document import DocumentRecord, DocumentChunk

logger = logging.getLogger("meridian.documents")

_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 3}


async def get_relevant_chunks_for_meeting(
    db: AsyncSession, meeting_id: int, query_text: str, limit: int = 6
) -> list[dict]:
    """Top-N релевантных чанков среди included+ready документов встречи.

    Источники: MeetingDocument(included=true) → DocumentRecord(status='ready') → DocumentChunk.
    """
    rows = (
        await db.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.text,
                DocumentChunk.page_number,
                DocumentChunk.sheet_name,
                DocumentRecord.original_name,
                MeetingDocumentRecord.priority,
            )
            .join(DocumentRecord, DocumentRecord.id == DocumentChunk.document_id)
            .join(
                MeetingDocumentRecord,
                MeetingDocumentRecord.document_id == DocumentRecord.id,
            )
            .where(
                MeetingDocumentRecord.session_id == meeting_id,
                MeetingDocumentRecord.included == True,  # noqa: E712
                DocumentRecord.status == "ready",
            )
        )
    ).all()
    if not rows:
        return []

    q = _tokens(query_text)
    scored: list[tuple[float, object]] = []
    for r in rows:
        priority_boost = (r.priority or 100) / 100000.0  # лёгкий приоритетный буст
        if not q:
            # пустой запрос → начало документов (по приоритету и порядку)
            score = priority_boost - r.chunk_index / 1_000_000.0
        else:
            ct = _tokens(r.text)
            overlap = len(q & ct)
            if overlap == 0:
                continue
            score = overlap / len(q) + priority_boost
            # бонус за вхождение фразы (биграммы запроса)
            low = r.text.lower()
            ql = query_text.lower()
            if len(ql) >= 6 and ql[:40] and ql[:40] in low:
                score += 0.2
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict] = []
    for score, r in scored[:limit]:
        out.append({
            "document_id": r.document_id,
            "document_name": r.original_name,
            "chunk_id": r.id,
            "text": r.text,
            "page_number": r.page_number,
            "sheet_name": r.sheet_name,
            "score": round(float(score), 4),
        })
    return out


def format_chunks_block(chunks: list[dict], max_chunks: int, max_chars: int) -> str:
    """Сформировать промпт-блок 'Релевантные фрагменты документов:' с лимитами."""
    if not chunks:
        return ""
    parts: list[str] = []
    total = 0
    for c in chunks[:max_chunks]:
        loc = ""
        if c.get("page_number"):
            loc = f" | Страница {c['page_number']}"
        elif c.get("sheet_name"):
            loc = f" | Лист: {c['sheet_name']}"
        header = f"[Документ: {c['document_name']}{loc}]"
        text = c["text"]
        if total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining < 200:
                break
            text = text[:remaining].rstrip() + "…"
        parts.append(f"{header}\n{text}")
        total += len(text)
        if total >= max_chars:
            break
    if not parts:
        return ""
    return "Релевантные фрагменты документов:\n\n" + "\n\n".join(parts)


async def build_meeting_doc_context(meeting_id: int, query_text: str) -> str:
    """Провайдер для SessionManager: вернуть готовый промпт-блок (или '').

    Открывает собственную сессию БД (вызывается из STT/LLM-движка).
    """
    settings = get_settings()
    try:
        async with async_session() as db:
            chunks = await get_relevant_chunks_for_meeting(
                db, meeting_id, query_text, limit=settings.document_context_max_chunks
            )
        return format_chunks_block(
            chunks, settings.document_context_max_chunks, settings.document_context_max_chars
        )
    except Exception as e:
        logger.error("doc context build failed for meeting %s: %s", meeting_id, e)
        return ""
