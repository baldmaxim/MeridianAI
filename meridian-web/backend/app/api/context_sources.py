"""API источников контекста встречи (Этап 8): previous meetings.

Просмотр — user_can_access_meeting. Изменение (add/remove/edit) — can_record_meeting
(creator/participant/edit/manage), как редактирование встречи. Добавить previous meeting
можно только при доступе к ней и не саму себя; дубли идемпотентны.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.meeting import MeetingSession
from ..models.context_source import MeetingContextSource
from ..auth.dependencies import get_current_user
from ..services.access import user_can_access_meeting, can_record_meeting
from ..services.previous_meeting_context import get_context_candidates, get_summary_cards
from ..services.meeting_room import room_registry
from ..schemas.context_source import (
    PreviousMeetingCandidate, MeetingContextSourceOut,
    MeetingContextSourceCreate, MeetingContextSourceUpdate, SOURCE_TYPES,
)

logger = logging.getLogger("meridian.context_sources")

router = APIRouter()


async def _notify_updated(meeting_id: int) -> None:
    room = room_registry.get_room(meeting_id)
    if room:
        try:
            await room.broadcast({"type": "meeting_context_sources_updated", "meeting_id": meeting_id})
        except Exception:
            pass


async def _to_out(db: AsyncSession, src: MeetingContextSource, user_id: int,
                  cards: dict | None = None) -> MeetingContextSourceOut:
    summary = None
    access_lost = False
    if src.source_type == "previous_meeting" and src.source_id is not None:
        if cards is not None:
            summary = cards.get(src.source_id)
        access_lost = not await user_can_access_meeting(db, user_id, src.source_id)
        if access_lost:
            summary = None  # не раскрываем данные при потере доступа
    return MeetingContextSourceOut(
        id=src.id, meeting_id=src.meeting_id, source_type=src.source_type, source_id=src.source_id,
        included=src.included, priority=src.priority, added_by_user_id=src.added_by_user_id,
        metadata_json=src.metadata_json, created_at=src.created_at, updated_at=src.updated_at,
        summary=summary, access_lost=access_lost,
    )


@router.get("/{meeting_id}/context-candidates", response_model=list[PreviousMeetingCandidate])
async def context_candidates(
    meeting_id: int,
    customer_id: int | None = Query(None),
    object_id: int | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(20),
    include_finalized_only: bool = Query(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    return await get_context_candidates(
        db, user.id, meeting_id, customer_id=customer_id, object_id=object_id,
        q=q, limit=limit, include_finalized_only=include_finalized_only,
    )


@router.get("/{meeting_id}/context-sources", response_model=list[MeetingContextSourceOut])
async def list_context_sources(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    rows = (await db.execute(
        select(MeetingContextSource).where(MeetingContextSource.meeting_id == meeting_id)
        .order_by(MeetingContextSource.priority.asc(), MeetingContextSource.created_at.asc())
    )).scalars().all()
    prev_ids = [s.source_id for s in rows if s.source_type == "previous_meeting" and s.source_id]
    cards = await get_summary_cards(db, prev_ids)
    return [await _to_out(db, s, user.id, cards) for s in rows]


@router.post("/{meeting_id}/context-sources", response_model=MeetingContextSourceOut)
async def add_context_source(
    meeting_id: int,
    data: MeetingContextSourceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Встреча не найдена")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения контекста встречи")
    if data.source_type not in SOURCE_TYPES:
        raise HTTPException(422, "Неизвестный source_type")

    if data.source_type == "previous_meeting":
        if data.source_id is None:
            raise HTTPException(422, "source_id обязателен для previous_meeting")
        if data.source_id == meeting_id:
            raise HTTPException(422, "Нельзя добавить текущую встречу как источник самой себя")
        prev = await db.get(MeetingSession, data.source_id)
        if not prev:
            raise HTTPException(404, "Прошлая встреча не найдена")
        if not await user_can_access_meeting(db, user.id, data.source_id):
            raise HTTPException(403, "Нет доступа к выбранной прошлой встрече")

    # идемпотентность: тот же (meeting, type, source_id) — обновить included/priority
    existing = None
    if data.source_id is not None:
        existing = (await db.execute(
            select(MeetingContextSource).where(
                MeetingContextSource.meeting_id == meeting_id,
                MeetingContextSource.source_type == data.source_type,
                MeetingContextSource.source_id == data.source_id,
            )
        )).scalar_one_or_none()

    if existing is not None:
        existing.included = data.included
        existing.priority = data.priority
        if data.metadata_json is not None:
            existing.metadata_json = data.metadata_json
        src = existing
    else:
        src = MeetingContextSource(
            meeting_id=meeting_id, source_type=data.source_type, source_id=data.source_id,
            included=data.included, priority=data.priority, metadata_json=data.metadata_json,
            added_by_user_id=user.id,
        )
        db.add(src)
    await db.flush()
    await db.refresh(src)
    prev_ids = [src.source_id] if (src.source_type == "previous_meeting" and src.source_id) else []
    cards = await get_summary_cards(db, prev_ids)
    out = await _to_out(db, src, user.id, cards)
    await _notify_updated(meeting_id)
    return out


@router.patch("/{meeting_id}/context-sources/{source_id}", response_model=MeetingContextSourceOut)
async def update_context_source(
    meeting_id: int,
    source_id: int,
    data: MeetingContextSourceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения контекста встречи")
    src = await db.get(MeetingContextSource, source_id)
    if not src or src.meeting_id != meeting_id:
        raise HTTPException(404, "Источник не найден")
    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(src, key, value)
    await db.flush()
    await db.refresh(src)
    prev_ids = [src.source_id] if (src.source_type == "previous_meeting" and src.source_id) else []
    cards = await get_summary_cards(db, prev_ids)
    out = await _to_out(db, src, user.id, cards)
    await _notify_updated(meeting_id)
    return out


@router.delete("/{meeting_id}/context-sources/{source_id}")
async def delete_context_source(
    meeting_id: int,
    source_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения контекста встречи")
    src = await db.get(MeetingContextSource, source_id)
    if not src or src.meeting_id != meeting_id:
        raise HTTPException(404, "Источник не найден")
    await db.delete(src)
    await db.flush()
    await _notify_updated(meeting_id)
    return {"ok": True}
