"""Извлечение кандидатов знаний после финализации (Этап 7, job learning_extract).

Кандидаты сохраняются как pending — НЕ применяются автоматически. Ошибка extraction не
ломает финализацию встречи (только learning_status=error).
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import async_session
from ..models.meeting import MeetingSession, TranscriptSegmentRecord
from ..models.directory import Customer, ProjectObject
from ..models.knowledge import LearningCandidate
from ..schemas.learning import (
    LearningExtractionResult, EVENT_TYPES, TECHNIQUES, SCOPES,
)
from ..services.jobs import enqueue
from ..services.api_keys import load_api_keys
from ..services.suggestion_parser import extract_json_from_text
from ..services.learning_dedup import existing_keys, candidate_keys
from ..core.llm.client import LLMClient
from ..core.llm.learning_prompt import SYSTEM_PROMPT, build_user_prompt, build_repair_prompt

logger = logging.getLogger("meridian.learning")


async def request_learning_extraction(db: AsyncSession, meeting_id: int) -> bool:
    settings = get_settings()
    if not settings.learning_extraction_enabled:
        return False
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        return False
    meeting.learning_status = "queued"
    meeting.learning_error = None
    await enqueue(db, "learning_extract", {"meeting_id": meeting_id})
    return True


async def enqueue_learning(meeting_id: int) -> None:
    async with async_session() as db:
        if await request_learning_extraction(db, meeting_id):
            await db.commit()


# --- coercion / scope safety ---

def _str(v, n=2000):
    return str(v or "").strip()[:n]


def _list_str(v):
    if not isinstance(v, list):
        return []
    return [_str(x, 300) for x in v if _str(x, 300)]


def _scope_safe(scope: str, meeting, trait: bool = False) -> str | None:
    scope = scope if scope in SCOPES else ("customer" if trait else "global")
    if scope == "object" and not meeting.object_id:
        scope = "customer" if meeting.customer_id else (None if trait else "global")
    if scope == "customer" and not meeting.customer_id:
        scope = None if trait else "global"
    return scope


def _coerce_payload(ctype: str, payload: dict, meeting) -> dict | None:
    """Очистить/коэрцировать payload по типу. None = отбросить кандидата."""
    p = payload or {}
    if ctype == "term":
        term = _str(p.get("term"), 300)
        if not term or len(term) < 2:
            return None
        scope = _scope_safe(p.get("scope", "global"), meeting)
        if scope is None:
            return None
        return {"term": term, "definition": _str(p.get("definition")), "aliases": _list_str(p.get("aliases")), "scope": scope}
    if ctype == "trigger_phrase":
        phrase = _str(p.get("phrase"), 500)
        if not phrase:
            return None
        et = str(p.get("event_type", "")).lower()
        scope = _scope_safe(p.get("scope", "global"), meeting)
        if scope is None:
            return None
        return {"phrase": phrase, "event_type": et if et in EVENT_TYPES else "other",
                "recommended_reaction": _str(p.get("recommended_reaction")), "scope": scope}
    if ctype == "playbook":
        situation = _str(p.get("situation"))
        phrase = _str(p.get("recommended_phrase"))
        if not situation or not phrase:
            return None
        tech = str(p.get("technique", "")).lower()
        scope = _scope_safe(p.get("scope", "global"), meeting)
        if scope is None:
            return None
        return {"situation": situation, "recommended_phrase": phrase,
                "technique": tech if tech in TECHNIQUES else "other",
                "ask_in_return": _list_str(p.get("ask_in_return")), "risks": _list_str(p.get("risks")), "scope": scope}
    if ctype == "counterparty_trait":
        trait = _str(p.get("trait"))
        if not trait:
            return None
        scope = _scope_safe(p.get("scope", "customer"), meeting, trait=True)
        if scope is None:
            return None  # нет customer/object — особенность некуда привязать
        return {"trait": trait, "evidence": _str(p.get("evidence")),
                "recommended_strategy": _str(p.get("recommended_strategy")), "scope": scope}
    if ctype == "forbidden_phrase":
        por = _str(p.get("phrase_or_risk"))
        if not por:
            return None
        scope = _scope_safe(p.get("scope", "global"), meeting)
        if scope is None:
            return None
        return {"phrase_or_risk": por, "better_alternative": _str(p.get("better_alternative")),
                "reason": _str(p.get("reason")), "scope": scope}
    return None


# --- inputs ---

async def _gather(db: AsyncSession, meeting) -> tuple[str, str, str]:
    settings = get_settings()
    customer = await db.get(Customer, meeting.customer_id) if meeting.customer_id else None
    obj = await db.get(ProjectObject, meeting.object_id) if meeting.object_id else None
    meta = []
    if customer:
        meta.append(f"Заказчик: {customer.name}")
    if obj:
        meta.append(f"Объект: {obj.name}")
    if meeting.meeting_topic:
        meta.append(f"Тема: {meeting.meeting_topic}")
    if meeting.title:
        meta.append(f"Название: {meeting.title}")
    if meeting.micro_summary:
        meta.append(f"Кратко: {meeting.micro_summary}")
    if meeting.tags_json:
        meta.append(f"Теги: {meeting.tags_json}")
    meeting_block = "\n".join(meta)

    protocol_block = meeting.protocol_markdown or ""
    if len(protocol_block) > 8000:
        protocol_block = protocol_block[:8000]

    segs = (await db.execute(
        select(TranscriptSegmentRecord)
        .where(TranscriptSegmentRecord.session_id == meeting.id)
        .order_by(TranscriptSegmentRecord.wall_clock.asc())
    )).scalars().all()
    transcript = "\n".join(f"{s.speaker_label or s.speaker_id}: {s.text}" for s in segs)
    cap = settings.learning_context_max_transcript_chars
    if len(transcript) > cap:
        half = cap // 2
        transcript = transcript[:half] + "\n…\n" + transcript[-half:]
    return meeting_block, protocol_block, transcript


async def _existing_block(db: AsyncSession, owner_id: int) -> str:
    """Краткий список уже утверждённых знаний (для anti-dup в промпте)."""
    lines = []
    for ctype, label in (("term", "Термины"), ("trigger_phrase", "Триггеры"),
                         ("playbook", "Playbooks"), ("counterparty_trait", "Особенности"),
                         ("forbidden_phrase", "Нежелательные")):
        keys = await existing_keys(db, owner_id, ctype)
        if keys:
            lines.append(f"{label}: " + "; ".join(list(keys)[:30]))
    return "\n".join(lines)


# --- job handler ---

async def handle_learning_extract(payload: dict) -> None:
    meeting_id = payload["meeting_id"]
    settings = get_settings()

    async with async_session() as db:
        meeting = await db.get(MeetingSession, meeting_id)
        if not meeting:
            return
        meeting.learning_status = "running"
        await db.commit()

    try:
        async with async_session() as db:
            meeting = await db.get(MeetingSession, meeting_id)
            meeting_block, protocol_block, transcript = await _gather(db, meeting)
            existing = await _existing_block(db, meeting.created_by_user_id or meeting.user_id)
            owner_id = meeting.created_by_user_id or meeting.user_id
            m_customer, m_object = meeting.customer_id, meeting.object_id

        if not transcript.strip() and not protocol_block.strip():
            await _set_status(meeting_id, "completed", None)
            return

        api_keys = await load_api_keys()
        key = api_keys.get("openrouter")
        if not key:
            await _set_status(meeting_id, "error", "LLM недоступна: нет ключа OpenRouter")
            return

        client = LLMClient(api_key=key, model=settings.learning_model, temperature=0.2,
                           max_tokens=4000, timeout=settings.learning_extraction_timeout_seconds)
        client.set_system_prompt(SYSTEM_PROMPT)
        prompt = build_user_prompt(meeting_block, protocol_block, transcript, existing,
                                   settings.learning_extraction_max_candidates)
        raw = await client.get_suggestion_async(prompt, max_tokens=4000)

        data = _parse(raw)
        if data is None and settings.learning_extraction_repair_enabled and raw:
            repaired = await client.get_suggestion_async(build_repair_prompt(raw), max_tokens=4000)
            data = _parse(repaired)
        if data is None:
            await _set_status(meeting_id, "error", "LLM вернула невалидный JSON")
            return

        result = LearningExtractionResult(**data)

        # persist (dedup + threshold + scope-safety)
        async with async_session() as db:
            meeting = await db.get(MeetingSession, meeting_id)
            seen_keys: dict[str, set[str]] = {}
            saved = 0
            for cand in result.candidates[:settings.learning_extraction_max_candidates]:
                ctype = cand.candidate_type
                if ctype not in ("term", "trigger_phrase", "playbook", "counterparty_trait", "forbidden_phrase"):
                    continue
                if not (cand.source_text or "").strip():
                    continue  # §: source_text обязателен
                if cand.confidence is not None and cand.confidence < settings.learning_extraction_min_confidence:
                    continue
                clean = _coerce_payload(ctype, cand.payload, meeting)
                if clean is None:
                    continue
                if ctype not in seen_keys:
                    seen_keys[ctype] = await existing_keys(db, owner_id, ctype)
                keys = candidate_keys(ctype, clean)
                if any(k in seen_keys[ctype] for k in keys):
                    continue  # дубль
                for k in keys:
                    seen_keys[ctype].add(k)

                # scope для записи candidate: customer/object из встречи если scope их требует
                scope = clean.get("scope", "global")
                cust = m_customer if scope in ("customer", "object") else None
                objc = m_object if scope == "object" else None
                db.add(LearningCandidate(
                    owner_user_id=owner_id,
                    customer_id=cust, object_id=objc, meeting_id=meeting_id,
                    candidate_type=ctype,
                    title=cand.title or keys[0][:200],
                    payload_json=json.dumps(clean, ensure_ascii=False),
                    source_text=cand.source_text,
                    source_refs_json=json.dumps([r.model_dump() for r in cand.source_refs], ensure_ascii=False),
                    confidence=cand.confidence,
                    status="pending",
                ))
                saved += 1
            meeting.learning_status = "completed"
            meeting.learning_error = None
            await db.commit()
        logger.info("learning_extract: meeting %s → %d candidates", meeting_id, saved)

    except Exception as e:
        logger.error("learning_extract: meeting %s failed: %s", meeting_id, e)
        await _set_status(meeting_id, "error", str(e)[:300])


def _parse(raw):
    js = extract_json_from_text(raw)
    if js is None:
        return None
    try:
        data = json.loads(js)
        return data if isinstance(data, dict) and isinstance(data.get("candidates"), list) else None
    except (ValueError, TypeError):
        return None


async def _set_status(meeting_id: int, status: str, error: str | None):
    async with async_session() as db:
        meeting = await db.get(MeetingSession, meeting_id)
        if meeting:
            meeting.learning_status = status
            meeting.learning_error = error
            await db.commit()
