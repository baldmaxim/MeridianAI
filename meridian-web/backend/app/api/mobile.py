"""Мобильный кабинет API (Этап 3): компактные список и карточка встречи.

Все эндпоинты ограничены видимостью Этапа 1 (accessible_meeting_filter /
user_can_access_meeting) — лишние встречи не раскрываются.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
import json as _json

from ..models.meeting import MeetingSession, TranscriptSegmentRecord, MeetingDocumentRecord
from ..models.directory import Customer, ProjectObject, MeetingParticipant
from ..models.document import DocumentRecord, DocumentChunk
from ..models.protocol import MeetingDecision, MeetingActionItem, MeetingRisk, MeetingOpenQuestion
from ..schemas.mobile import (
    MobileMeetingListItem,
    MobileMeetingDetail,
    MobileParticipant,
    MobileTranscriptLine,
)
from ..schemas.document import MeetingDocumentItem
from ..services.access import (
    accessible_meeting_filter,
    user_can_access_meeting,
    can_record_meeting,
    current_user_meeting_role,
)
from ..services.meeting_room import room_registry, compute_live_state

router = APIRouter()


def _room_flags(meeting_id: int):
    room = room_registry.get_room(meeting_id)
    is_live = bool(room and room.session.is_listening)
    phone = bool(room and any(c.device_role == "phone" for c in room.connections.values()))
    desktop = bool(room and any(c.device_role == "desktop" for c in room.connections.values()))
    return is_live, phone, desktop


@router.get("/meetings", response_model=list[MobileMeetingListItem])
async def mobile_meetings(
    status: str | None = Query(None),
    customer_id: int | None = Query(None),
    object_id: int | None = Query(None),
    q: str | None = Query(None),
    only_live: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Компактный список доступных пользователю встреч (по правилам Этапа 1)."""
    stmt = (
        select(MeetingSession, Customer.name.label("customer_name"), ProjectObject.name.label("object_name"))
        .outerjoin(Customer, Customer.id == MeetingSession.customer_id)
        .outerjoin(ProjectObject, ProjectObject.id == MeetingSession.object_id)
        .where(accessible_meeting_filter(user.id))
        .order_by(MeetingSession.started_at.desc())
        .limit(200)
    )
    if status:
        stmt = stmt.where(MeetingSession.status == status)
    if customer_id is not None:
        stmt = stmt.where(MeetingSession.customer_id == customer_id)
    if object_id is not None:
        stmt = stmt.where(MeetingSession.object_id == object_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            func.coalesce(MeetingSession.title, "").ilike(like)
            | func.coalesce(MeetingSession.meeting_topic, "").ilike(like)
        )

    rows = (await db.execute(stmt)).all()
    items: list[MobileMeetingListItem] = []
    for meeting, cname, oname in rows:
        is_live, phone, desktop = _room_flags(meeting.id)
        if only_live and not is_live:
            continue
        role = await current_user_meeting_role(db, user.id, meeting.id)
        can_rec = await can_record_meeting(db, user.id, meeting.id)
        items.append(MobileMeetingListItem(
            id=meeting.id,
            title=meeting.title,
            micro_summary=meeting.micro_summary,
            status=meeting.status,
            customer_id=meeting.customer_id,
            customer_name=cname,
            object_id=meeting.object_id,
            object_name=oname,
            meeting_topic=meeting.meeting_topic,
            started_at=meeting.started_at,
            ended_at=meeting.ended_at,
            created_at=meeting.started_at,
            created_by_user_id=meeting.created_by_user_id,
            current_user_role=role,
            can_record=can_rec,
            is_live=is_live,
            phone_connected=phone,
            desktop_connected=desktop,
            finalization_status=meeting.finalization_status,
            tags=_json.loads(meeting.tags_json) if meeting.tags_json else [],
        ))
    return items


@router.get("/meetings/{meeting_id}", response_model=MobileMeetingDetail)
async def mobile_meeting_detail(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Компактная карточка встречи для мобильного UI."""
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(status_code=403, detail="Нет доступа к встрече")

    customer = await db.get(Customer, meeting.customer_id) if meeting.customer_id else None
    obj = await db.get(ProjectObject, meeting.object_id) if meeting.object_id else None

    part_rows = (
        await db.execute(
            select(MeetingParticipant, User)
            .join(User, User.id == MeetingParticipant.user_id)
            .where(MeetingParticipant.meeting_id == meeting_id)
            .order_by(MeetingParticipant.created_at)
        )
    ).all()
    participants = [
        MobileParticipant(user_id=u.id, role=mp.role, email=u.email, display_name=u.display_name)
        for mp, u in part_rows
    ]

    seg_rows = (
        await db.execute(
            select(TranscriptSegmentRecord)
            .where(TranscriptSegmentRecord.session_id == meeting_id)
            .order_by(TranscriptSegmentRecord.wall_clock.desc())
            .limit(20)
        )
    ).scalars().all()
    recent = [
        MobileTranscriptLine(
            speaker=s.speaker_label or s.speaker_id,
            text=s.text,
            wall_clock=s.wall_clock,
        )
        for s in reversed(seg_rows)
    ]

    live = await compute_live_state(db, meeting, user.id)

    # документы встречи (read-only для мобильного)
    chunks_subq = (
        select(func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id == DocumentRecord.id)
        .correlate(DocumentRecord)
        .scalar_subquery()
    )
    doc_rows = (
        await db.execute(
            select(MeetingDocumentRecord, DocumentRecord, chunks_subq.label("cc"))
            .join(DocumentRecord, DocumentRecord.id == MeetingDocumentRecord.document_id)
            .where(
                MeetingDocumentRecord.session_id == meeting_id,
                MeetingDocumentRecord.document_id.isnot(None),
            )
            .order_by(MeetingDocumentRecord.priority.desc(), MeetingDocumentRecord.id)
        )
    ).all()
    documents = [
        MeetingDocumentItem(
            id=md.id, document_id=doc.id, original_name=doc.original_name, file_ext=doc.file_ext,
            status=doc.status, included=md.included, priority=md.priority, chunks_count=cc or 0,
            page_count=doc.page_count, sheet_count=doc.sheet_count, processing_error=doc.processing_error,
        )
        for md, doc, cc in doc_rows
    ]

    # Этап 5: протокол (если сформирован)
    decisions = (await db.execute(select(MeetingDecision).where(MeetingDecision.meeting_id == meeting_id).order_by(MeetingDecision.id))).scalars().all()
    actions = (await db.execute(select(MeetingActionItem).where(MeetingActionItem.meeting_id == meeting_id).order_by(MeetingActionItem.id))).scalars().all()
    risks = (await db.execute(select(MeetingRisk).where(MeetingRisk.meeting_id == meeting_id).order_by(MeetingRisk.id))).scalars().all()
    questions = (await db.execute(select(MeetingOpenQuestion).where(MeetingOpenQuestion.meeting_id == meeting_id).order_by(MeetingOpenQuestion.id))).scalars().all()

    def _ev(s):
        if not s:
            return []
        try:
            v = _json.loads(s)
            return v if isinstance(v, list) else []
        except (ValueError, TypeError):
            return []

    # Этап 8: выбранные прошлые встречи как контекст (read-only, только included)
    from ..models.context_source import MeetingContextSource
    from ..services.previous_meeting_context import get_summary_cards
    src_ids = (await db.execute(
        select(MeetingContextSource.source_id)
        .where(
            MeetingContextSource.meeting_id == meeting_id,
            MeetingContextSource.source_type == "previous_meeting",
            MeetingContextSource.included == True,  # noqa: E712
            MeetingContextSource.source_id.isnot(None),
        )
        .order_by(MeetingContextSource.priority.asc(), MeetingContextSource.created_at.asc())
    )).scalars().all()
    prev_cards = await get_summary_cards(db, list(src_ids))
    # только доступные пользователю прошлые встречи
    previous_context = []
    for pid in src_ids:
        if pid in prev_cards and await user_can_access_meeting(db, user.id, pid):
            previous_context.append(prev_cards[pid])

    from ..schemas.finalization import (
        ProtocolDecisionOut, ProtocolActionItemOut, ProtocolRiskOut, ProtocolOpenQuestionOut,
    )
    decisions_out = [ProtocolDecisionOut(id=d.id, text=d.text, status=d.status, evidence=_ev(d.evidence_json), created_at=d.created_at) for d in decisions]
    actions_out = [ProtocolActionItemOut(id=a.id, task=a.task, owner_text=a.owner_text, due_text=a.due_text, status=a.status, evidence=_ev(a.evidence_json), created_at=a.created_at) for a in actions]
    risks_out = [ProtocolRiskOut(id=r.id, text=r.text, severity=r.severity, evidence=_ev(r.evidence_json), created_at=r.created_at) for r in risks]
    questions_out = [ProtocolOpenQuestionOut(id=q.id, text=q.text, evidence=_ev(q.evidence_json), created_at=q.created_at) for q in questions]

    return MobileMeetingDetail(
        id=meeting.id,
        title=meeting.title,
        status=meeting.status,
        customer_id=meeting.customer_id,
        customer_name=customer.name if customer else None,
        object_id=meeting.object_id,
        object_name=obj.name if obj else None,
        meeting_topic=meeting.meeting_topic,
        meeting_notes=meeting.meeting_notes,
        negotiation_type=meeting.negotiation_type,
        meeting_role=meeting.meeting_role,
        opponent_weaknesses=meeting.opponent_weaknesses,
        micro_summary=meeting.micro_summary,
        started_at=meeting.started_at,
        ended_at=meeting.ended_at,
        created_by_user_id=meeting.created_by_user_id,
        participants=participants,
        can_current_user_record=live["can_current_user_record"],
        current_user_role=live["current_user_role"],
        live_state=live,
        recent_segments=recent,
        documents=documents,
        finalization_status=meeting.finalization_status,
        finalization_error=meeting.finalization_error,
        tags=_json.loads(meeting.tags_json) if meeting.tags_json else [],
        has_protocol=bool(meeting.protocol_markdown),
        decisions=decisions_out,
        action_items=actions_out,
        risks=risks_out,
        open_questions=questions_out,
        previous_context=previous_context,
    )
