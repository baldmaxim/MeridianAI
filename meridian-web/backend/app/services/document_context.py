"""DocumentContextService (Этап 4): подбор релевантных чанков документов встречи
для LLM-подсказок. MVP — лексический BM25 по основам слов DocumentChunk.

Готово к будущему переходу на embeddings/vector search: интерфейс
get_relevant_chunks_for_meeting() стабилен, меняется только реализация scoring.
"""

import logging
import math
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import async_session
from ..models.meeting import MeetingDocumentRecord
from ..models.document import DocumentRecord, DocumentChunk

logger = logging.getLogger("meridian.documents")

_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)
_STEM_LEN = 5
# Разговорные и служебные слова реплики: в договоре они случайно совпадают с чем угодно.
_STOP_WORDS = frozenset(
    "это эти этот эта этом этого того тем том там тут как так что чтобы если или либо для при "
    "про над под без через после перед между также тоже уже еще все всех весь вся всего каждый "
    "каждого каждой был была были будет будем будут есть нет них ним нам вам вас ваш вашу ваша "
    "ваше наш нашу наша они она оно его ему мне меня себя свой свою своих который которые "
    "которая только очень даже можно нужно надо сейчас завтра сегодня вчера здесь тогда когда "
    "пока".split()
)
# BM25: насыщение частоты слова и поправка на длину фрагмента.
_BM25_K1 = 1.2
_BM25_B = 0.75


def _stems(text: str) -> list[str]:
    """Основы слов: «удерживать», «удержание», «удерживает» → «удерж».

    Русские окончания иначе ломают совпадение: реплика «будем удерживать» не находила
    пункт договора «Застроитель ежемесячно удерживает 3%». Грубое усечение вместо
    морфологии — без новых зависимостей, коллизии гасит вес редкости слова.
    """
    words = _TOKEN_RE.findall((text or "").lower().replace("ё", "е"))
    return [w[:_STEM_LEN] for w in words if len(w) >= 3 and w not in _STOP_WORDS]


def _bm25_scores(query_text: str, texts: list[str]) -> list[float]:
    """BM25 по основам слов. Учитывает, сколько раз слово стоит во фрагменте:
    пункт, целиком посвящённый удержанию, важнее страницы, где оно упомянуто вскользь.
    Частые слова договора («работ», «договор») почти ничего не весят.
    """
    query = set(_stems(query_text))
    docs = [Counter(_stems(t)) for t in texts]
    if not query or not docs:
        return [0.0] * len(texts)
    n = len(docs)
    avg_len = (sum(sum(d.values()) for d in docs) / n) or 1.0
    idf = {}
    for term in query:
        df = sum(term in d for d in docs)
        idf[term] = math.log(1 + (n - df + 0.5) / (df + 0.5))
    scores = []
    for d in docs:
        norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * sum(d.values()) / avg_len)
        scores.append(sum(idf[t] * d[t] * (_BM25_K1 + 1) / (d[t] + norm) for t in query if d[t]))
    return scores


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

    has_query = bool(_stems(query_text))
    bm25 = _bm25_scores(query_text, [r.text for r in rows]) if has_query else []
    scored: list[tuple[float, object]] = []
    for i, r in enumerate(rows):
        priority_boost = (r.priority or 100) / 100000.0  # лёгкий приоритетный буст
        if not has_query:
            # пустой запрос → начало документов (по приоритету и порядку)
            score = priority_boost - r.chunk_index / 1_000_000.0
        else:
            if bm25[i] <= 0:
                continue
            score = bm25[i] + priority_boost
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
