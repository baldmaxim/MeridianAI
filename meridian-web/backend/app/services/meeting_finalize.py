"""Финализация встречи (Этап 5): фоновый job формирует протокол через LLM.

Встреча остаётся завершённой и доступной даже при ошибке LLM (status error/partial).
Протокол строится ТОЛЬКО по фактам транскрипта/контекста/документов.
"""

import json
import logging

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import async_session
from ..models.meeting import MeetingSession, TranscriptSegmentRecord, MeetingDocumentRecord
from ..models.directory import Customer, ProjectObject, MeetingParticipant
from ..models.document import DocumentRecord
from ..models.user import User
from ..models.protocol import MeetingDecision, MeetingActionItem, MeetingRisk, MeetingOpenQuestion
from ..schemas.finalization import MeetingFinalizationResult
from ..services.jobs import enqueue
from ..services.api_keys import load_api_keys
from ..services.document_context import get_relevant_chunks_for_meeting, format_chunks_block
from ..core.llm.client import LLMClient
from ..core.llm.finalization_prompt import SYSTEM_PROMPT, build_user_prompt, build_repair_prompt
from datetime import datetime

logger = logging.getLogger("meridian.finalize")


async def request_finalization(db: AsyncSession, meeting_id: int) -> bool:
    """Поставить встречу в очередь финализации. Коммитит ВЫЗЫВАЮЩИЙ. Возвращает, поставлено ли."""
    settings = get_settings()
    if not settings.meeting_finalization_enabled:
        return False
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        return False
    meeting.finalization_status = "queued"
    meeting.finalization_error = None
    await enqueue(db, "meeting_finalize", {"meeting_id": meeting_id})
    return True


async def enqueue_finalization(meeting_id: int) -> None:
    """Вариант с собственной сессией (для MeetingRoom)."""
    async with async_session() as db:
        ok = await request_finalization(db, meeting_id)
        if ok:
            await db.commit()


# --- парсинг JSON ---

def _parse_json_lenient(text: str | None) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    # вырезать первый {...} если вокруг есть мусор
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


# --- сбор входных данных ---

def _fmt_tc(seconds: float | None) -> str:
    s = int(seconds or 0)
    return f"{s // 60:02d}:{s % 60:02d}"


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max(500, max_chars // 2 - 60)
    return text[:half] + "\n\n[… середина транскрипта опущена для объёма …]\n\n" + text[-half:]


async def _gather_inputs(db: AsyncSession, meeting: MeetingSession) -> tuple[str, str, str, list[str]]:
    settings = get_settings()

    customer = await db.get(Customer, meeting.customer_id) if meeting.customer_id else None
    obj = await db.get(ProjectObject, meeting.object_id) if meeting.object_id else None
    part_rows = (
        await db.execute(
            select(User.display_name, User.email)
            .join(MeetingParticipant, MeetingParticipant.user_id == User.id)
            .where(MeetingParticipant.meeting_id == meeting.id)
        )
    ).all()
    participants = [dn or em for dn, em in part_rows]

    meta = []
    if customer:
        meta.append(f"Заказчик: {customer.name}")
    if obj:
        meta.append(f"Объект: {obj.name}")
    if meeting.meeting_topic:
        meta.append(f"Тема: {meeting.meeting_topic}")
    if meeting.meeting_notes:
        meta.append(f"Заметки/цели: {meeting.meeting_notes}")
    if meeting.negotiation_type:
        meta.append(f"Тип переговоров: {meeting.negotiation_type}")
    if meeting.meeting_role:
        meta.append(f"Наша роль: {meeting.meeting_role}")
    if meeting.opponent_weaknesses:
        meta.append(f"Слабые стороны оппонента: {meeting.opponent_weaknesses}")
    if meeting.started_at:
        meta.append(f"Начало: {meeting.started_at.isoformat()}")
    if meeting.ended_at:
        meta.append(f"Окончание: {meeting.ended_at.isoformat()}")
    if participants:
        meta.append(f"Участники: {', '.join(participants)}")
    meeting_block = "\n".join(meta) if meta else "(метаданные не заданы)"

    # transcript
    segs = (
        await db.execute(
            select(TranscriptSegmentRecord)
            .where(TranscriptSegmentRecord.session_id == meeting.id)
            .order_by(TranscriptSegmentRecord.wall_clock.asc())
        )
    ).scalars().all()
    transcript_text = "\n".join(
        f"[{_fmt_tc(s.start_time)}] {s.speaker_label or s.speaker_id}: {s.text}" for s in segs
    )
    transcript_text = _truncate(transcript_text, settings.meeting_finalization_max_transcript_chars)

    # documents (имена + релевантные чанки, ограничено)
    doc_names = (
        await db.execute(
            select(DocumentRecord.original_name)
            .join(MeetingDocumentRecord, MeetingDocumentRecord.document_id == DocumentRecord.id)
            .where(
                MeetingDocumentRecord.session_id == meeting.id,
                MeetingDocumentRecord.included == True,  # noqa: E712
            )
        )
    ).scalars().all()
    chunks = await get_relevant_chunks_for_meeting(db, meeting.id, meeting.meeting_topic or "", limit=6)
    documents_block = ""
    if doc_names:
        documents_block = "Документы: " + ", ".join(doc_names) + "\n\n"
    documents_block += format_chunks_block(chunks, max_chunks=6, max_chars=settings.meeting_finalization_max_document_chars)

    return meeting_block, transcript_text, documents_block.strip(), list(doc_names)


# --- сохранение ---

def _evidence_json(ev_list) -> str:
    return json.dumps([e.model_dump() for e in ev_list], ensure_ascii=False)


async def _save_result(db: AsyncSession, meeting: MeetingSession, result: MeetingFinalizationResult,
                       status: str) -> None:
    meeting.title = result.title or meeting.title or (meeting.meeting_topic or "")[:90] or \
        f"Встреча {meeting.started_at.strftime('%d.%m.%Y %H:%M')}"
    meeting.micro_summary = result.micro_summary or meeting.micro_summary
    meeting.tags_json = json.dumps(result.tags, ensure_ascii=False)
    meeting.protocol_markdown = result.protocol_markdown
    meeting.protocol_json = json.dumps(result.model_dump(), ensure_ascii=False)
    meeting.summary_json = json.dumps({
        "summary_points": [p.model_dump() for p in result.summary_points],
        "important_quotes": [q.model_dump() for q in result.important_quotes],
        "document_references": [d.model_dump() for d in result.document_references],
    }, ensure_ascii=False)

    # перегенерация: удалить старые строки
    for model in (MeetingDecision, MeetingActionItem, MeetingRisk, MeetingOpenQuestion):
        await db.execute(delete(model).where(model.meeting_id == meeting.id))

    for d in result.decisions:
        if not d.text.strip():
            continue
        db.add(MeetingDecision(meeting_id=meeting.id, text=d.text, status=d.status, evidence_json=_evidence_json(d.evidence)))
    for a in result.action_items:
        if not a.task.strip():
            continue
        db.add(MeetingActionItem(meeting_id=meeting.id, task=a.task, owner_text=a.owner, due_text=a.due, status=a.status, evidence_json=_evidence_json(a.evidence)))
    for r in result.risks:
        if not r.text.strip():
            continue
        db.add(MeetingRisk(meeting_id=meeting.id, text=r.text, severity=r.severity, evidence_json=_evidence_json(r.evidence)))
    for q in result.open_questions:
        if not q.text.strip():
            continue
        db.add(MeetingOpenQuestion(meeting_id=meeting.id, text=q.text, evidence_json=_evidence_json(q.evidence)))

    meeting.finalization_status = status
    meeting.finalization_error = None if status == "completed" else meeting.finalization_error
    meeting.finalized_at = datetime.utcnow()
    meeting.is_finalized = True


# --- job handler ---

async def handle_meeting_finalize(payload: dict) -> None:
    meeting_id = payload["meeting_id"]
    settings = get_settings()

    async with async_session() as db:
        meeting = await db.get(MeetingSession, meeting_id)
        if not meeting:
            logger.warning("finalize: meeting %s not found", meeting_id)
            return
        meeting.finalization_status = "running"
        await db.commit()

    try:
        async with async_session() as db:
            meeting = await db.get(MeetingSession, meeting_id)
            meeting_block, transcript_text, documents_block, doc_names = await _gather_inputs(db, meeting)

        # пустой транскрипт → минимальный partial (без LLM)
        if not transcript_text.strip():
            async with async_session() as db:
                meeting = await db.get(MeetingSession, meeting_id)
                meeting.finalization_status = "partial"
                meeting.finalization_error = "Пустой транскрипт — протокол не сформирован"
                if not meeting.title:
                    meeting.title = (meeting.meeting_topic or "")[:90] or f"Встреча {meeting.started_at.strftime('%d.%m.%Y %H:%M')}"
                meeting.micro_summary = meeting.micro_summary or "Нет транскрипта для протокола"
                meeting.finalized_at = datetime.utcnow()
                meeting.is_finalized = True
                await db.commit()
            logger.info("finalize: meeting %s partial (empty transcript)", meeting_id)
            return

        api_keys = await load_api_keys()
        key = api_keys.get("openrouter")
        if not key:
            await _set_error(meeting_id, "LLM недоступна: не настроен ключ OpenRouter")
            return

        client = LLMClient(api_key=key, model=settings.finalization_model, temperature=0.2,
                           max_tokens=6000, timeout=settings.meeting_finalization_timeout_seconds)
        client.set_system_prompt(SYSTEM_PROMPT)
        user_prompt = build_user_prompt(meeting_block, transcript_text, documents_block)

        raw = None
        for attempt in range(max(1, settings.meeting_finalization_retry_attempts)):
            raw = await client.get_suggestion_async(user_prompt, max_tokens=6000)
            if raw:
                break
        if not raw:
            await _set_error(meeting_id, "LLM не вернула ответ")
            return

        data = _parse_json_lenient(raw)
        if data is None:
            # одна попытка ремонта
            repaired = await client.get_suggestion_async(build_repair_prompt(raw), max_tokens=6000)
            data = _parse_json_lenient(repaired)
        if data is None:
            await _set_error(meeting_id, "LLM вернула невалидный JSON")
            return

        try:
            result = MeetingFinalizationResult(**data)
        except Exception as e:
            await _set_error(meeting_id, f"Ошибка валидации протокола: {str(e)[:200]}")
            return

        # partial, если по сути пусто
        has_content = bool(
            result.protocol_markdown.strip() or result.summary_points or result.decisions
            or result.action_items or result.risks or result.open_questions
        )
        status = "completed" if has_content else "partial"

        async with async_session() as db:
            meeting = await db.get(MeetingSession, meeting_id)
            if status == "partial":
                meeting.finalization_error = "LLM вернула неполный протокол"
            await _save_result(db, meeting, result, status)
            # Этап 7: авто-извлечение кандидатов знаний (только при наличии транскрипта).
            # Ошибка learning_extract не ломает финализацию — это отдельный job.
            from .learning_extract import request_learning_extraction
            await request_learning_extraction(db, meeting_id)
            await db.commit()
        logger.info("finalize: meeting %s %s (decisions=%d, actions=%d, risks=%d)",
                    meeting_id, status, len(result.decisions), len(result.action_items), len(result.risks))

    except Exception as e:
        logger.error("finalize: meeting %s failed: %s", meeting_id, e)
        await _set_error(meeting_id, str(e)[:300])


async def _set_error(meeting_id: int, message: str) -> None:
    async with async_session() as db:
        meeting = await db.get(MeetingSession, meeting_id)
        if meeting:
            meeting.finalization_status = "error"
            meeting.finalization_error = message
            meeting.finalized_at = datetime.utcnow()
            meeting.is_finalized = True
            await db.commit()
