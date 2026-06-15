"""Предыдущие встречи как контекст (Этап 8).

В live/finalization prompts попадают ТОЛЬКО компактные итоги выбранных прошлых встреч
(title/micro_summary/tags/решения/задачи/риски/вопросы/цитаты), НЕ полные транскрипты.
Только included=true источники; доступ перепроверяется на момент сборки (потеря доступа →
данные не раскрываются). Авто-выбор отсутствует — included ставит пользователь.
"""

import json
import logging

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import async_session
from ..models.meeting import MeetingSession
from ..models.directory import Customer, ProjectObject
from ..models.protocol import MeetingDecision, MeetingActionItem, MeetingRisk, MeetingOpenQuestion
from ..models.context_source import MeetingContextSource
from ..services.access import accessible_meeting_filter, user_can_access_meeting
from ..schemas.context_source import PreviousMeetingSummaryCard, PreviousMeetingCandidate

logger = logging.getLogger("meridian.prev_context")


def _tags(tags_json: str | None) -> list[str]:
    if not tags_json:
        return []
    try:
        v = json.loads(tags_json)
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def _counts_subqueries():
    dec = (select(func.count(MeetingDecision.id)).where(MeetingDecision.meeting_id == MeetingSession.id)
           .correlate(MeetingSession).scalar_subquery())
    act = (select(func.count(MeetingActionItem.id)).where(MeetingActionItem.meeting_id == MeetingSession.id)
           .correlate(MeetingSession).scalar_subquery())
    rsk = (select(func.count(MeetingRisk.id)).where(MeetingRisk.meeting_id == MeetingSession.id)
           .correlate(MeetingSession).scalar_subquery())
    oq = (select(func.count(MeetingOpenQuestion.id)).where(MeetingOpenQuestion.meeting_id == MeetingSession.id)
          .correlate(MeetingSession).scalar_subquery())
    return dec, act, rsk, oq


def _card_from_row(r) -> PreviousMeetingSummaryCard:
    return PreviousMeetingSummaryCard(
        meeting_id=r.id, title=r.title, micro_summary=r.micro_summary,
        customer_id=r.customer_id, customer_name=r.customer_name,
        object_id=r.object_id, object_name=r.object_name,
        status=r.status, finalization_status=r.finalization_status,
        started_at=r.started_at, ended_at=r.ended_at,
        tags=_tags(r.tags_json), has_protocol=bool(r.has_protocol),
        decisions_count=r.dec_count or 0, action_items_count=r.act_count or 0,
        risks_count=r.rsk_count or 0, open_questions_count=r.oq_count or 0,
    )


def _base_card_select():
    dec, act, rsk, oq = _counts_subqueries()
    return (
        select(
            MeetingSession.id, MeetingSession.title, MeetingSession.micro_summary,
            MeetingSession.customer_id, MeetingSession.object_id,
            MeetingSession.status, MeetingSession.finalization_status,
            MeetingSession.started_at, MeetingSession.ended_at, MeetingSession.tags_json,
            (MeetingSession.protocol_markdown.isnot(None)).label("has_protocol"),
            Customer.name.label("customer_name"),
            ProjectObject.name.label("object_name"),
            dec.label("dec_count"), act.label("act_count"),
            rsk.label("rsk_count"), oq.label("oq_count"),
        )
        .outerjoin(Customer, Customer.id == MeetingSession.customer_id)
        .outerjoin(ProjectObject, ProjectObject.id == MeetingSession.object_id)
    )


async def get_summary_cards(db: AsyncSession, meeting_ids: list[int]) -> dict[int, PreviousMeetingSummaryCard]:
    """Карточки-итоги для набора встреч (без проверки доступа — вызывающий уже проверил)."""
    if not meeting_ids:
        return {}
    rows = (await db.execute(_base_card_select().where(MeetingSession.id.in_(meeting_ids)))).all()
    return {r.id: _card_from_row(r) for r in rows}


async def get_context_candidates(
    db: AsyncSession, user_id: int, meeting_id: int,
    customer_id: int | None = None, object_id: int | None = None,
    q: str | None = None, limit: int | None = None, include_finalized_only: bool = True,
) -> list[PreviousMeetingCandidate]:
    """Доступные пользователю завершённые встречи как кандидаты контекста (приоритет: объект→заказчик→финал→свежесть)."""
    settings = get_settings()
    limit = limit or settings.previous_meetings_candidates_limit

    cur = await db.get(MeetingSession, meeting_id)
    cur_customer = cur.customer_id if cur else None
    cur_object = cur.object_id if cur else None

    stmt = _base_card_select().where(
        MeetingSession.id != meeting_id,            # не текущая встреча
        MeetingSession.is_active == False,          # только завершённые  # noqa: E712
        accessible_meeting_filter(user_id),         # только доступные
    )
    if include_finalized_only:
        stmt = stmt.where(MeetingSession.finalization_status.in_(("completed", "partial")))
    if customer_id is not None:
        stmt = stmt.where(MeetingSession.customer_id == customer_id)
    if object_id is not None:
        stmt = stmt.where(MeetingSession.object_id == object_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            func.coalesce(MeetingSession.title, "").ilike(like)
            | func.coalesce(MeetingSession.meeting_topic, "").ilike(like)
            | func.coalesce(MeetingSession.micro_summary, "").ilike(like)
        )

    # приоритет: тот же объект → тот же заказчик → completed → свежесть
    same_obj = case((MeetingSession.object_id == cur_object, 0), else_=1) if cur_object is not None else case((True, 1))
    same_cust = case((MeetingSession.customer_id == cur_customer, 0), else_=1) if cur_customer is not None else case((True, 1))
    fin_rank = case((MeetingSession.finalization_status == "completed", 0),
                    (MeetingSession.finalization_status == "partial", 1), else_=2)
    stmt = stmt.order_by(same_obj, same_cust, fin_rank, MeetingSession.started_at.desc()).limit(limit)

    rows = (await db.execute(stmt)).all()

    # уже прикреплённые previous_meeting источники
    added = set((await db.execute(
        select(MeetingContextSource.source_id).where(
            MeetingContextSource.meeting_id == meeting_id,
            MeetingContextSource.source_type == "previous_meeting",
            MeetingContextSource.source_id.isnot(None),
        )
    )).scalars().all())

    out: list[PreviousMeetingCandidate] = []
    for r in rows:
        card = _card_from_row(r)
        out.append(PreviousMeetingCandidate(**card.model_dump(), already_added=r.id in added))
    return out


# --- сборка компактного блока для prompt ---

async def _gather_protocol(db: AsyncSession, mid: int) -> dict:
    decisions = (await db.execute(select(MeetingDecision.text, MeetingDecision.status)
                 .where(MeetingDecision.meeting_id == mid).order_by(MeetingDecision.id).limit(12))).all()
    actions = (await db.execute(select(MeetingActionItem.task, MeetingActionItem.owner_text, MeetingActionItem.due_text)
               .where(MeetingActionItem.meeting_id == mid).order_by(MeetingActionItem.id).limit(12))).all()
    risks = (await db.execute(select(MeetingRisk.text, MeetingRisk.severity)
             .where(MeetingRisk.meeting_id == mid).order_by(MeetingRisk.id).limit(12))).all()
    questions = (await db.execute(select(MeetingOpenQuestion.text)
                 .where(MeetingOpenQuestion.meeting_id == mid).order_by(MeetingOpenQuestion.id).limit(12))).scalars().all()
    return {"decisions": decisions, "actions": actions, "risks": risks, "questions": questions}


def _quotes_and_refs(summary_json: str | None) -> tuple[list, list]:
    if not summary_json:
        return [], []
    try:
        v = json.loads(summary_json)
    except (ValueError, TypeError):
        return [], []
    quotes = v.get("important_quotes") or []
    refs = v.get("document_references") or []
    return (quotes if isinstance(quotes, list) else []), (refs if isinstance(refs, list) else [])


def _fmt_meeting_block(idx: int, card: PreviousMeetingSummaryCard, proto: dict,
                       quotes: list, per_max: int) -> str:
    lines: list[str] = [f"{idx}. [Meeting #{card.meeting_id}] {card.title or 'Без названия'}"]
    co = []
    if card.customer_name:
        co.append(f"заказчик {card.customer_name}")
    if card.object_name:
        co.append(f"объект {card.object_name}")
    if co:
        lines.append(f"   Заказчик/объект: {', '.join(co)}")
    if card.started_at:
        lines.append(f"   Дата: {card.started_at.strftime('%d.%m.%Y')}")
    if card.micro_summary:
        lines.append(f"   Кратко: {card.micro_summary}")
    if card.tags:
        lines.append(f"   Теги: {', '.join(card.tags)}")

    if proto["decisions"]:
        lines.append("   Решения:")
        lines += [f"   - {t} [{s}]" for t, s in proto["decisions"]]
    if proto["actions"]:
        lines.append("   Задачи:")
        for task, owner, due in proto["actions"]:
            extra = " ".join(p for p in [f"— {owner}" if owner else "", f"(срок: {due})" if due else ""] if p)
            lines.append(f"   - {task} {extra}".rstrip())
    if proto["risks"]:
        lines.append("   Риски:")
        lines += [f"   - {t} [{sev}]" for t, sev in proto["risks"]]
    if proto["questions"]:
        lines.append("   Открытые вопросы:")
        lines += [f"   - {t}" for t in proto["questions"]]
    if quotes:
        lines.append("   Важные цитаты:")
        for qd in quotes[:6]:
            if isinstance(qd, dict):
                txt = qd.get("quote") or qd.get("text") or ""
                spk = qd.get("speaker")
                lines.append(f"   - {(spk + ': ') if spk else ''}{txt}")
            else:
                lines.append(f"   - {qd}")

    block = "\n".join(lines)
    if len(block) > per_max:
        block = block[:per_max].rstrip() + "\n   [часть сведений опущена]"
    return block


async def build_previous_context_block(
    db: AsyncSession, meeting_id: int, viewer_user_id: int | None = None,
    max_chars: int | None = None,
) -> str:
    """Собрать блок «ПРЕДЫДУЩИЕ ВСТРЕЧИ…» на ПЕРЕДАННОЙ сессии (или '')."""
    settings = get_settings()
    if not settings.previous_meetings_context_enabled:
        return ""
    max_chars = max_chars or settings.previous_meetings_context_max_chars
    per_max = settings.previous_meetings_context_per_meeting_max_chars

    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        return ""
    viewer = viewer_user_id or meeting.created_by_user_id or meeting.user_id

    sources = (await db.execute(
        select(MeetingContextSource).where(
            MeetingContextSource.meeting_id == meeting_id,
            MeetingContextSource.source_type == "previous_meeting",
            MeetingContextSource.included == True,  # noqa: E712
            MeetingContextSource.source_id.isnot(None),
        ).order_by(MeetingContextSource.priority.asc(), MeetingContextSource.created_at.asc())
    )).scalars().all()
    if not sources:
        return ""

    prev_ids = [s.source_id for s in sources][: settings.previous_meetings_context_max_meetings]
    cards = await get_summary_cards(db, prev_ids)

    blocks: list[str] = []
    total = 0
    idx = 0
    truncated = False
    for pid in prev_ids:
        card = cards.get(pid)
        if card is None:
            continue
        # перепроверка доступа: при потере доступа не раскрываем данные
        if not await user_can_access_meeting(db, viewer, pid):
            continue
        prev = await db.get(MeetingSession, pid)
        proto = await _gather_protocol(db, pid)
        quotes, _refs = _quotes_and_refs(prev.summary_json if prev else None)
        idx += 1
        block = _fmt_meeting_block(idx, card, proto, quotes, per_max)
        if total + len(block) > max_chars:
            truncated = True
            break
        blocks.append(block)
        total += len(block)

    if not blocks:
        return ""
    header = "ПРЕДЫДУЩИЕ ВСТРЕЧИ, ВЫБРАННЫЕ КАК КОНТЕКСТ:"
    body = "\n\n".join(blocks)
    if truncated:
        body += "\n\n[часть сведений опущена]"
    return f"{header}\n{body}"


async def get_previous_meeting_context_for_prompt(
    meeting_id: int, query_text: str | None = None, max_chars: int | None = None,
    viewer_user_id: int | None = None,
) -> str:
    """Провайдер для SessionManager: открывает свою сессию и собирает блок (или '')."""
    try:
        async with async_session() as db:
            return await build_previous_context_block(db, meeting_id, viewer_user_id, max_chars)
    except Exception as e:
        logger.error("previous context build failed for meeting %s: %s", meeting_id, e)
        return ""
