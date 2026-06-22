"""Провайдер контекста писем PayHub для LLM-подсказок (RAG-augmentation).

Резолвит PayHub project_id из объекта встречи (MeetingSession.object_id →
ProjectObject.payhub_project_id), ищет письма во внешнем pgvector-хранилище и формирует
промпт-блок. Источник ОТДЕЛЬНЫЙ от внутренних RAG-папок (services/rag_context.py).

Ручной выбор писем (прикреплённые к встрече в meeting_context_sources, source_type='letter')
имеет приоритет над авто-поиском: если письма выбраны вручную — блок строится только из них.

Никогда не падает: при любой ошибке/выключенном модуле возвращает ''. Чтобы не жечь платный
Yandex в живом диалоге — per-meeting троттлинг (повтор результата в пределах окна).
"""

from __future__ import annotations

import json
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..core.rag_letters import RagHit, build_rag_context, search_letters
from ..database import async_session
from ..models.context_source import MeetingContextSource
from ..models.directory import ProjectObject
from ..models.meeting import MeetingSession
from ..schemas.letters import MeetingLetterAttach, MeetingLetterOut

logger = logging.getLogger("meridian.rag_letters")

# Тип источника прикреплённого письма в meeting_context_sources (source_id=NULL, снапшот в meta).
SOURCE_TYPE_LETTER = "letter"
# Ограничение текста снапшота письма (символов) — фрагмент уже компактный, но подстрахуемся.
_SNAPSHOT_TEXT_MAX = 6000
# Поля снапшота письма (camelCase — как LetterSearchHit/RagHit.to_dict).
_SNAPSHOT_FIELDS = (
    "chunkId", "letterId", "subject", "regNumber", "number", "customerNumber",
    "direction", "letterDate", "projectId", "pageFrom", "pageTo", "text",
)

# meeting_id -> (expires_at, block) — короткий per-meeting кэш результата (троттлинг).
_throttle: dict[int, tuple[float, str]] = {}


async def _resolve_payhub_project_id(meeting_id: int) -> int | None:
    """PayHub project_id для встречи (или None → искать по всему корпусу)."""
    try:
        async with async_session() as db:
            meeting = await db.get(MeetingSession, meeting_id)
            if meeting is None or meeting.object_id is None:
                return None
            obj = await db.get(ProjectObject, meeting.object_id)
            return obj.payhub_project_id if obj else None
    except Exception as e:
        logger.warning("rag_letters: resolve project_id failed for meeting %s: %s", meeting_id, e)
        return None


# ── снапшот письма ↔ JSON / RagHit / схема ────────────────────────────────────

def _parse_snapshot(metadata_json: str | None) -> dict | None:
    if not metadata_json:
        return None
    try:
        data = json.loads(metadata_json)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get("chunkId") else None


def _snapshot_from_attach(data: MeetingLetterAttach) -> dict:
    snap = {f: getattr(data, f) for f in _SNAPSHOT_FIELDS}
    if snap.get("text"):
        snap["text"] = snap["text"][:_SNAPSHOT_TEXT_MAX]
    return snap


def _snap_to_hit(snap: dict) -> RagHit:
    return RagHit(
        chunk_id=snap.get("chunkId") or "",
        letter_id=snap.get("letterId"),
        subject=snap.get("subject"),
        reg_number=snap.get("regNumber"),
        number=snap.get("number"),
        customer_number=snap.get("customerNumber"),
        direction=snap.get("direction"),
        letter_date=snap.get("letterDate"),
        project_id=snap.get("projectId"),
        page_from=snap.get("pageFrom"),
        page_to=snap.get("pageTo"),
        text=snap.get("text") or "",
        score=0.0,
    )


def _src_to_out(src: MeetingContextSource) -> MeetingLetterOut | None:
    snap = _parse_snapshot(src.metadata_json)
    if snap is None:
        return None
    return MeetingLetterOut(
        sourceId=src.id, included=src.included, priority=src.priority,
        **{f: snap.get(f) for f in _SNAPSHOT_FIELDS},
    )


# ── прикреплённые письма встречи (CRUD) ───────────────────────────────────────

async def list_attached_letters(db: AsyncSession, meeting_id: int) -> list[MeetingLetterOut]:
    srcs = (await db.execute(
        select(MeetingContextSource).where(
            MeetingContextSource.meeting_id == meeting_id,
            MeetingContextSource.source_type == SOURCE_TYPE_LETTER,
        ).order_by(MeetingContextSource.priority.asc(), MeetingContextSource.created_at.asc())
    )).scalars().all()
    out: list[MeetingLetterOut] = []
    for s in srcs:
        item = _src_to_out(s)
        if item is not None:
            out.append(item)
    return out


async def attach_letter_to_meeting(
    db: AsyncSession, meeting_id: int, data: MeetingLetterAttach, user_id: int,
) -> MeetingLetterOut:
    """Прикрепить письмо к встрече (снапшот в metadata_json). Дедуп по chunkId (idempotent)."""
    snap = _snapshot_from_attach(data)
    # source_id=NULL → partial-unique не срабатывает, дедуп вручную по chunkId.
    existing = (await db.execute(
        select(MeetingContextSource).where(
            MeetingContextSource.meeting_id == meeting_id,
            MeetingContextSource.source_type == SOURCE_TYPE_LETTER,
        )
    )).scalars().all()
    src = next((s for s in existing if (_parse_snapshot(s.metadata_json) or {}).get("chunkId") == data.chunkId), None)
    if src is not None:
        src.included = data.included
        src.priority = data.priority
        src.metadata_json = json.dumps(snap, ensure_ascii=False)
    else:
        src = MeetingContextSource(
            meeting_id=meeting_id, source_type=SOURCE_TYPE_LETTER, source_id=None,
            included=data.included, priority=data.priority, added_by_user_id=user_id,
            metadata_json=json.dumps(snap, ensure_ascii=False),
        )
        db.add(src)
    await db.flush()
    await db.refresh(src)
    out = _src_to_out(src)
    if out is None:
        raise ValueError("Некорректный снапшот письма")
    return out


async def update_attached_letter(
    db: AsyncSession, src: MeetingContextSource,
    included: bool | None = None, priority: int | None = None,
) -> MeetingLetterOut:
    if included is not None:
        src.included = included
    if priority is not None:
        src.priority = priority
    await db.flush()
    await db.refresh(src)
    out = _src_to_out(src)
    if out is None:
        raise ValueError("Некорректный снапшот письма")
    return out


async def detach_letter_from_meeting(db: AsyncSession, src: MeetingContextSource) -> None:
    await db.delete(src)
    await db.flush()


async def _load_pinned_letters(meeting_id: int) -> list[RagHit]:
    """Прикреплённые вручную письма встречи (included=true) → RagHit. Открывает свою сессию."""
    async with async_session() as db:
        srcs = (await db.execute(
            select(MeetingContextSource).where(
                MeetingContextSource.meeting_id == meeting_id,
                MeetingContextSource.source_type == SOURCE_TYPE_LETTER,
                MeetingContextSource.included.is_(True),
            ).order_by(MeetingContextSource.priority.asc(), MeetingContextSource.created_at.asc())
        )).scalars().all()
    hits: list[RagHit] = []
    for s in srcs:
        snap = _parse_snapshot(s.metadata_json)
        if snap is not None:
            hits.append(_snap_to_hit(snap))
    return hits


async def build_meeting_letters_context(meeting_id: int, query_text: str = "") -> str:
    """Провайдер для SessionManager: промпт-блок переписки (или '').

    Если к встрече прикреплены письма вручную — блок строится ТОЛЬКО из них (без Yandex, без
    троттлинга). Иначе — авто-поиск по реплике (внешний пул + Yandex). Никогда не бросает.
    """
    s = get_settings()
    if not s.letters_rag_effective_enabled:
        return ""

    # Ручной выбор имеет приоритет над авто-поиском.
    try:
        pinned = await _load_pinned_letters(meeting_id)
    except Exception as e:
        logger.warning("rag_letters: load pinned failed for meeting %s: %s", meeting_id, e)
        pinned = []
    if pinned:
        return build_rag_context(pinned)

    query = (query_text or "").strip()
    if not query:
        return ""

    now = time.time()
    cached = _throttle.get(meeting_id)
    if cached and cached[0] > now:
        return cached[1]

    try:
        project_id = await _resolve_payhub_project_id(meeting_id)
        hits = await search_letters(query, k=s.letters_context_k, project_id=project_id)
        block = build_rag_context(hits)
    except Exception as e:
        logger.error("rag_letters: build context failed for meeting %s: %s", meeting_id, e)
        block = ""

    _throttle[meeting_id] = (now + max(0, s.letters_context_throttle_seconds), block)
    return block
