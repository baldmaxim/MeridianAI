"""Провайдер контекста писем PayHub для LLM-подсказок (RAG-augmentation).

Резолвит PayHub project_id из объекта встречи (MeetingSession.object_id →
ProjectObject.payhub_project_id), ищет письма во внешнем pgvector-хранилище и формирует
промпт-блок. Источник ОТДЕЛЬНЫЙ от внутренних RAG-папок (services/rag_context.py).

Никогда не падает: при любой ошибке/выключенном модуле возвращает ''. Чтобы не жечь платный
Yandex в живом диалоге — per-meeting троттлинг (повтор результата в пределах окна).
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select

from ..config import get_settings
from ..core.rag_letters import build_rag_context, search_letters
from ..database import async_session
from ..models.directory import ProjectObject
from ..models.meeting import MeetingSession

logger = logging.getLogger("meridian.rag_letters")

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


async def build_meeting_letters_context(meeting_id: int, query_text: str = "") -> str:
    """Провайдер для SessionManager: промпт-блок переписки (или '').

    Открывает собственные ресурсы (внешний пул + Yandex). Никогда не бросает исключений.
    """
    s = get_settings()
    if not s.letters_rag_effective_enabled:
        return ""
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
