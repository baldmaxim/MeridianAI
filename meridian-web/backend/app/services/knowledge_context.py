"""Контекст утверждённой базы знаний для live-подсказок (Этап 7).

В подсказки попадают ТОЛЬКО approved-элементы, в scope встречи (object > customer > global).
Кандидаты (pending) и archived — никогда. Провайдер для SessionManager: build_meeting_knowledge_context.
"""

import json
import logging

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session
from ..models.meeting import MeetingSession
from ..models.knowledge import (
    GlossaryTerm, TriggerPhrase, NegotiationPlaybook, CounterpartyTrait, ForbiddenPhrase,
)

logger = logging.getLogger("meridian.knowledge")

PER_TYPE_LIMIT = 12
MAX_BLOCK_CHARS = 6000


def _scope_filter(model, owner_id: int, customer_id: int | None, object_id: int | None):
    """approved + (object O) | (customer C, object NULL) | (global: оба NULL)."""
    conds = [model.customer_id.is_(None) & model.object_id.is_(None)]  # global
    if customer_id is not None:
        conds.append((model.customer_id == customer_id) & model.object_id.is_(None))
    if object_id is not None:
        conds.append(model.object_id == object_id)
    return and_(model.owner_user_id == owner_id, model.status == "approved", or_(*conds))


async def get_relevant_knowledge(db: AsyncSession, owner_id: int,
                                 customer_id: int | None, object_id: int | None) -> dict:
    out: dict[str, list] = {}
    for key, model in (("terms", GlossaryTerm), ("triggers", TriggerPhrase),
                       ("playbooks", NegotiationPlaybook), ("traits", CounterpartyTrait),
                       ("forbidden", ForbiddenPhrase)):
        rows = (await db.execute(
            select(model).where(_scope_filter(model, owner_id, customer_id, object_id)).limit(PER_TYPE_LIMIT)
        )).scalars().all()
        out[key] = rows
    return out


def format_knowledge_block(items: dict) -> str:
    parts: list[str] = []

    terms = items.get("terms") or []
    if terms:
        lines = []
        for t in terms:
            al = ""
            if t.aliases_json:
                try:
                    a = json.loads(t.aliases_json)
                    if a:
                        al = f" (синонимы: {', '.join(a)})"
                except (ValueError, TypeError):
                    al = ""
            lines.append(f"- {t.term}{al}: {t.definition}")
        parts.append("Термины:\n" + "\n".join(lines))

    triggers = items.get("triggers") or []
    if triggers:
        lines = [f"- Если звучит «{t.phrase}» ({t.event_type}) → {t.recommended_reaction}" for t in triggers]
        parts.append("Триггерные фразы и реакция:\n" + "\n".join(lines))

    playbooks = items.get("playbooks") or []
    if playbooks:
        lines = []
        for p in playbooks:
            extra = ""
            if p.ask_in_return_json:
                try:
                    ar = json.loads(p.ask_in_return_json)
                    if ar:
                        extra = " | взамен просить: " + "; ".join(ar)
                except (ValueError, TypeError):
                    pass
            lines.append(f"- Ситуация: {p.situation} → сказать: «{p.recommended_phrase}» [{p.technique}]{extra}")
        parts.append("Playbooks (проверенные ходы):\n" + "\n".join(lines))

    traits = items.get("traits") or []
    if traits:
        lines = [f"- {t.trait}" + (f" → стратегия: {t.recommended_strategy}" if t.recommended_strategy else "") for t in traits]
        parts.append("Особенности контрагента:\n" + "\n".join(lines))

    forbidden = items.get("forbidden") or []
    if forbidden:
        lines = [f"- НЕ говорить: {f.phrase_or_risk}" + (f" → лучше: «{f.better_alternative}»" if f.better_alternative else "") for f in forbidden]
        parts.append("Нежелательные формулировки:\n" + "\n".join(lines))

    if not parts:
        return ""
    block = "\n\n".join(parts)
    return block[:MAX_BLOCK_CHARS]


async def build_meeting_knowledge_context_from_db(
    db: AsyncSession, meeting_id: int, max_chars: int | None = None,
) -> str:
    """Блок утверждённой базы знаний на ПЕРЕДАННОЙ сессии (для Context Pack/preview)."""
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        return ""
    owner_id = meeting.created_by_user_id or meeting.user_id
    items = await get_relevant_knowledge(db, owner_id, meeting.customer_id, meeting.object_id)
    block = format_knowledge_block(items)
    if max_chars and len(block) > max_chars:
        block = block[:max_chars]
    return block


async def build_meeting_knowledge_context(meeting_id: int, query_text: str = "") -> str:
    """Провайдер для SessionManager: блок утверждённой базы знаний (или '')."""
    try:
        async with async_session() as db:
            return await build_meeting_knowledge_context_from_db(db, meeting_id)
    except Exception as e:
        logger.error("knowledge context build failed for meeting %s: %s", meeting_id, e)
        return ""
