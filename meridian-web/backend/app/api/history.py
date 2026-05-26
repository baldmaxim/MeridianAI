"""Meeting history API routes."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("meridian.history")

from ..database import get_db
from ..models.user import User
from ..models.meeting import MeetingSession, TranscriptSegmentRecord, MeetingSuggestion, MeetingDocumentRecord
from ..core.context.document_loader import DOC_TYPE_LABELS
from ..schemas.meeting import (
    MeetingListItem,
    MeetingDetailResponse,
    MeetingTitleUpdate,
    MeetingBatchDelete,
    TranscriptSegmentResponse,
    MeetingSuggestionResponse,
    MeetingDocumentResponse,
)
from ..auth.dependencies import get_current_user

router = APIRouter()


@router.get("", response_model=list[MeetingListItem])
async def list_meetings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List finished meetings for current user."""
    # Subqueries for counts
    seg_count = (
        select(func.count(TranscriptSegmentRecord.id))
        .where(TranscriptSegmentRecord.session_id == MeetingSession.id)
        .correlate(MeetingSession)
        .scalar_subquery()
    )
    sug_count = (
        select(func.count(MeetingSuggestion.id))
        .where(MeetingSuggestion.session_id == MeetingSession.id)
        .correlate(MeetingSession)
        .scalar_subquery()
    )

    result = await db.execute(
        select(
            MeetingSession.id,
            MeetingSession.title,
            MeetingSession.meeting_topic,
            MeetingSession.negotiation_type,
            MeetingSession.started_at,
            MeetingSession.ended_at,
            seg_count.label("segment_count"),
            sug_count.label("suggestion_count"),
        )
        .where(
            MeetingSession.user_id == user.id,
            MeetingSession.is_active == False,
        )
        .order_by(MeetingSession.started_at.desc())
    )

    rows = result.all()
    return [
        MeetingListItem(
            id=r.id,
            title=r.title,
            meeting_topic=r.meeting_topic,
            negotiation_type=r.negotiation_type,
            started_at=r.started_at,
            ended_at=r.ended_at,
            segment_count=r.segment_count or 0,
            suggestion_count=r.suggestion_count or 0,
        )
        for r in rows
    ]


@router.post("/batch/delete")
async def batch_delete_meetings(
    data: MeetingBatchDelete,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple meetings at once."""
    logger.info(f"[batch-delete] user={user.id} ids={data.ids}")
    if not data.ids:
        return {"ok": True, "deleted": 0}

    # Check FK pragma
    fk_result = await db.execute(text("PRAGMA foreign_keys"))
    fk_val = fk_result.scalar()
    logger.info(f"[batch-delete] PRAGMA foreign_keys = {fk_val}")

    result = await db.execute(
        select(MeetingSession).where(
            MeetingSession.id.in_(data.ids),
            MeetingSession.user_id == user.id,
        )
    )
    meetings = result.scalars().all()
    logger.info(f"[batch-delete] found {len(meetings)} meetings to delete (requested {len(data.ids)})")

    for m in meetings:
        logger.info(f"[batch-delete] deleting meeting id={m.id} title={m.title!r}")
        await db.delete(m)

    await db.flush()
    logger.info(f"[batch-delete] flush done, deleted={len(meetings)}")
    return {"ok": True, "deleted": len(meetings)}


@router.get("/{meeting_id}", response_model=MeetingDetailResponse)
async def get_meeting_detail(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full meeting detail with segments and suggestions."""
    result = await db.execute(
        select(MeetingSession).where(
            MeetingSession.id == meeting_id,
            MeetingSession.user_id == user.id,
        )
    )
    meeting = result.scalar_one_or_none()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Load segments
    seg_result = await db.execute(
        select(TranscriptSegmentRecord)
        .where(TranscriptSegmentRecord.session_id == meeting_id)
        .order_by(TranscriptSegmentRecord.wall_clock.asc())
    )
    segments = [
        TranscriptSegmentResponse.model_validate(s)
        for s in seg_result.scalars().all()
    ]

    # Load suggestions
    sug_result = await db.execute(
        select(MeetingSuggestion)
        .where(MeetingSuggestion.session_id == meeting_id)
        .order_by(MeetingSuggestion.created_at.asc())
    )
    suggestions = [
        MeetingSuggestionResponse.model_validate(s)
        for s in sug_result.scalars().all()
    ]

    # Load documents
    doc_result = await db.execute(
        select(MeetingDocumentRecord)
        .where(MeetingDocumentRecord.session_id == meeting_id)
        .order_by(MeetingDocumentRecord.created_at.asc())
    )
    documents = [
        MeetingDocumentResponse(
            filename=d.filename,
            doc_type=d.doc_type,
            doc_type_label=DOC_TYPE_LABELS.get(d.doc_type, d.doc_type),
            page_count=d.page_count,
        )
        for d in doc_result.scalars().all()
    ]

    return MeetingDetailResponse(
        id=meeting.id,
        title=meeting.title,
        meeting_topic=meeting.meeting_topic,
        meeting_notes=meeting.meeting_notes,
        negotiation_type=meeting.negotiation_type,
        meeting_role=meeting.meeting_role,
        opponent_weaknesses=meeting.opponent_weaknesses,
        started_at=meeting.started_at,
        ended_at=meeting.ended_at,
        segments=segments,
        suggestions=suggestions,
        documents=documents,
    )


@router.put("/{meeting_id}/title")
async def update_meeting_title(
    meeting_id: int,
    data: MeetingTitleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update meeting title."""
    result = await db.execute(
        select(MeetingSession).where(
            MeetingSession.id == meeting_id,
            MeetingSession.user_id == user.id,
        )
    )
    meeting = result.scalar_one_or_none()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    meeting.title = data.title
    await db.flush()
    return {"ok": True}


@router.post("/{meeting_id}/continue")
async def continue_meeting(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a finished meeting so it can be continued."""
    result = await db.execute(
        select(MeetingSession).where(
            MeetingSession.id == meeting_id,
            MeetingSession.user_id == user.id,
        )
    )
    meeting = result.scalar_one_or_none()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    meeting.is_active = True
    meeting.ended_at = None
    await db.flush()
    return {"ok": True, "meeting_id": meeting_id}


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a meeting and all related data."""
    logger.info(f"[delete] user={user.id} meeting_id={meeting_id}")
    result = await db.execute(
        select(MeetingSession).where(
            MeetingSession.id == meeting_id,
            MeetingSession.user_id == user.id,
        )
    )
    meeting = result.scalar_one_or_none()
    if not meeting:
        logger.warning(f"[delete] meeting {meeting_id} not found for user {user.id}")
        raise HTTPException(status_code=404, detail="Meeting not found")

    logger.info(f"[delete] deleting meeting id={meeting.id} title={meeting.title!r}")
    await db.delete(meeting)
    await db.flush()
    logger.info(f"[delete] flush done for meeting {meeting_id}")
    return {"ok": True}
