"""Сборка Context Pack из провайдеров (Этап 6).

Live-сборка (assemble_live_context_pack) принимает уже собранные строки от SessionManager
и не ходит в БД. Static-сборка (assemble_static_context_pack_for_meeting) собирает контекст
из БД для preview-эндпоинта (без LLM, без websocket-комнаты, без live-транскрипта).

Порядок блоков фиксирован и объясним; бюджеты — из config (per-mode + per-block).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.meeting import MeetingSession
from ..core.llm.context_pack import (
    ContextPack, ContextBlock, ContextPackMode, ContextBlockKind, apply_pack_budget,
)

logger = logging.getLogger("meridian.context_pack")


def context_pack_max_chars_for_mode(mode: ContextPackMode) -> int:
    s = get_settings()
    return {
        "auto": s.context_pack_auto_max_chars,
        "manual": s.context_pack_manual_max_chars,
        "strengthen": s.context_pack_strengthen_max_chars,
        "preview": s.context_pack_manual_max_chars,
    }.get(mode, s.context_pack_manual_max_chars)


def build_provider_block(
    kind: ContextBlockKind,
    title: str,
    content: str,
    *,
    enabled: bool = True,
    reason: str | None = None,
    priority: int = 100,
    max_chars: int | None = None,
    source_count: int = 0,
    meta: dict | None = None,
) -> ContextBlock:
    return ContextBlock(
        kind=kind, title=title, content=content or "", enabled=enabled and bool(content),
        reason=reason, priority=priority, max_chars=max_chars,
        source_count=source_count, meta=meta or {},
    )


def build_meeting_context_block(
    topic: str = "",
    notes: str = "",
    negotiation_type: str = "",
    meeting_role: str = "",
    opponent_weaknesses: str = "",
) -> ContextBlock:
    lines: list[str] = []
    if topic:
        lines.append(f"Тема: {topic}")
    if notes:
        lines.append(f"Цели/условия: {notes}")
    if negotiation_type:
        lines.append(f"Тип переговоров: {negotiation_type}")
    if meeting_role:
        lines.append(f"Наша роль: {meeting_role}")
    if opponent_weaknesses:
        lines.append(f"Слабые стороны оппонента: {opponent_weaknesses}")
    content = "\n".join(lines)
    s = get_settings()
    return build_provider_block(
        "meeting_context", "Контекст встречи", content,
        enabled=bool(content),
        reason=None if content else "Контекст встречи не заполнен",
        priority=10, max_chars=s.context_pack_meeting_context_max_chars,
        source_count=1 if content else 0,
    )


def build_dialog_block(
    mode: ContextPackMode,
    recent_dialog: str = "",
    full_transcript: str = "",
) -> ContextBlock:
    s = get_settings()
    if mode == "strengthen":
        return build_provider_block(
            "full_transcript", "Полный транскрипт", full_transcript,
            enabled=bool(full_transcript), priority=20,
            max_chars=s.context_pack_full_transcript_max_chars,
        )
    return build_provider_block(
        "recent_dialog", "Последние реплики", recent_dialog,
        enabled=bool(recent_dialog), priority=20,
        max_chars=s.context_pack_recent_dialog_max_chars,
    )


def _ai_on(ai_settings: dict | None, key: str) -> bool:
    if not ai_settings:
        return True
    return bool(ai_settings.get(key, True))


def assemble_live_context_pack(
    *,
    mode: ContextPackMode,
    query_text: str,
    meeting_context_block: str,
    recent_dialog: str = "",
    full_transcript: str = "",
    document_context: str = "",
    rag_context: str = "",
    knowledge_context: str = "",
    previous_meetings_context: str = "",
    ai_settings: dict | None = None,
) -> ContextPack:
    """Собрать ContextPack из готовых строк. Не ходит в БД, не вызывает LLM."""
    s = get_settings()

    # meeting_context
    mc = build_provider_block(
        "meeting_context", "Контекст встречи", meeting_context_block,
        enabled=bool(meeting_context_block),
        reason=None if meeting_context_block else "Контекст встречи не заполнен",
        priority=10, max_chars=s.context_pack_meeting_context_max_chars,
        source_count=1 if meeting_context_block else 0,
    )

    # document
    doc_on = _ai_on(ai_settings, "document_context_enabled")
    document = build_provider_block(
        "document", "Документы встречи", document_context if doc_on else "",
        enabled=doc_on and bool(document_context),
        reason=("Отключено в настройках встречи" if not doc_on
                else (None if document_context else "Нет релевантных фрагментов")),
        priority=40, max_chars=s.context_pack_document_max_chars,
        source_count=(document_context or "").count("[Документ:"),
    )

    # rag — v1 зависит от document_context_enabled + глобального rag_context_enabled
    rag_global = bool(getattr(s, "rag_context_enabled", True))
    rag_on = doc_on and rag_global
    rag = build_provider_block(
        "rag", "RAG-папки", rag_context if rag_on else "",
        enabled=rag_on and bool(rag_context),
        reason=("RAG отключён в конфигурации" if not rag_global
                else ("Отключено в настройках встречи" if not doc_on
                      else (None if rag_context else "Нет релевантных фрагментов"))),
        priority=50, max_chars=s.context_pack_rag_max_chars,
        source_count=(rag_context or "").count("[RAG-папка:"),
    )

    # knowledge
    kn_on = _ai_on(ai_settings, "knowledge_context_enabled")
    knowledge = build_provider_block(
        "knowledge", "Утверждённая база знаний", knowledge_context if kn_on else "",
        enabled=kn_on and bool(knowledge_context),
        reason=("Отключено в настройках встречи" if not kn_on
                else (None if knowledge_context else "Нет утверждённых элементов")),
        priority=60, max_chars=s.context_pack_knowledge_max_chars,
    )

    # previous
    pm_on = _ai_on(ai_settings, "previous_meetings_context_enabled")
    previous = build_provider_block(
        "previous_meeting", "Предыдущие встречи как контекст",
        previous_meetings_context if pm_on else "",
        enabled=pm_on and bool(previous_meetings_context),
        reason=("Отключено в настройках встречи" if not pm_on
                else (None if previous_meetings_context else "Не выбраны прошлые встречи")),
        priority=70, max_chars=s.context_pack_previous_max_chars,
        source_count=(previous_meetings_context or "").count("[Meeting #"),
    )

    dialog = build_dialog_block(mode, recent_dialog=recent_dialog, full_transcript=full_transcript)

    pack = ContextPack(
        mode=mode, query_text=query_text,
        blocks=[mc, document, rag, knowledge, previous, dialog],
        max_chars=context_pack_max_chars_for_mode(mode),
    )
    return apply_pack_budget(pack)


async def assemble_static_context_pack_for_meeting(
    db: AsyncSession,
    *,
    meeting_id: int,
    viewer_user_id: int,
    mode: ContextPackMode = "manual",
    query_text: str = "",
) -> ContextPack:
    """Статическая сборка контекста из БД для preview (без live-транскрипта и LLM).

    Доступ проверяет вызывающий (API). Каждый provider защищён try/except — частичная
    ошибка не валит весь pack.
    """
    s = get_settings()
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return apply_pack_budget(ContextPack(
            mode=mode, query_text=query_text, blocks=[],
            max_chars=context_pack_max_chars_for_mode(mode),
        ))

    meeting_context = build_meeting_context_block(
        topic=meeting.meeting_topic or "", notes=meeting.meeting_notes or "",
        negotiation_type=meeting.negotiation_type or "", meeting_role=meeting.meeting_role or "",
        opponent_weaknesses=meeting.opponent_weaknesses or "",
    ).content

    document_context = ""
    try:
        from .document_context import get_relevant_chunks_for_meeting, format_chunks_block
        chunks = await get_relevant_chunks_for_meeting(
            db, meeting_id, query_text, limit=s.document_context_max_chunks
        )
        document_context = format_chunks_block(
            chunks, s.document_context_max_chunks, s.document_context_max_chars
        )
    except Exception as e:
        logger.error("preview document block failed for meeting %s: %s", meeting_id, e)

    rag_context = ""
    if getattr(s, "rag_context_enabled", True):
        try:
            from .rag_context import get_relevant_rag_chunks_for_meeting, format_rag_chunks_block
            rchunks = await get_relevant_rag_chunks_for_meeting(
                db, meeting_id, query_text, limit=s.rag_context_max_chunks
            )
            rag_context = format_rag_chunks_block(
                rchunks, s.rag_context_max_chunks, s.rag_context_max_chars
            )
        except Exception as e:
            logger.error("preview rag block failed for meeting %s: %s", meeting_id, e)

    knowledge_context = ""
    try:
        from .knowledge_context import build_meeting_knowledge_context_from_db
        knowledge_context = await build_meeting_knowledge_context_from_db(
            db, meeting_id, max_chars=s.context_pack_knowledge_max_chars
        )
    except Exception as e:
        logger.error("preview knowledge block failed for meeting %s: %s", meeting_id, e)

    previous_context = ""
    try:
        from .previous_meeting_context import build_previous_context_block
        previous_context = await build_previous_context_block(
            db, meeting_id, viewer_user_id, max_chars=s.context_pack_previous_max_chars
        )
    except Exception as e:
        logger.error("preview previous block failed for meeting %s: %s", meeting_id, e)

    # preview показывает доступный контекст независимо от live AI-тогглов (ai_settings=None)
    pack = assemble_live_context_pack(
        mode=mode, query_text=query_text,
        meeting_context_block=meeting_context,
        recent_dialog="", full_transcript="",
        document_context=document_context, rag_context=rag_context,
        knowledge_context=knowledge_context, previous_meetings_context=previous_context,
        ai_settings=None,
    )

    # live-реплик в preview нет — честный disabled-блок с понятной причиной
    for b in pack.blocks:
        if b.kind in ("recent_dialog", "full_transcript") and not b.content:
            b.enabled = False
            b.reason = ("Полный live-транскрипт доступен в активной комнате"
                        if b.kind == "full_transcript"
                        else "Live-реплики доступны только во время встречи")
    return pack
