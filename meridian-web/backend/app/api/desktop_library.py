# -*- coding: utf-8 -*-
"""Библиотека десктоп-приложения: все встречи сайта и проекты, только чтение.

Приложение ходит с токеном устройства (как в desktop.py) и показывает не только свои
встречи, но и всё, что видно на сайте. Доступ — теми же правилами, что и на сайте
(services/access): никаких своих проверок.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.context.document_loader import DOC_TYPE_LABELS
from ..database import get_db
from ..models.desktop import DesktopMeetingLink
from ..models.directory import Customer, ProjectObject
from ..models.meeting import MeetingDocumentRecord, MeetingSession, TranscriptSegmentRecord
from ..schemas.desktop import (
    DesktopCustomer,
    DesktopDocumentOut,
    DesktopLibraryItem,
    DesktopMeetingView,
    DesktopObjectOut,
    DesktopSegmentOut,
)
from ..services.access import accessible_meeting_filter, user_can_access_meeting
from .desktop import Device

router = APIRouter()

MAX_LIMIT = 500


def _library_select(user_id: int):
    """SELECT встречи + имена заказчика/объекта + признаки связи с приложением (без N+1)."""
    own_uuid = (
        select(func.min(DesktopMeetingLink.client_uuid))
        .where(DesktopMeetingLink.meeting_id == MeetingSession.id,
               DesktopMeetingLink.user_id == user_id)
        .correlate(MeetingSession)
        .scalar_subquery()
    )
    any_link = (
        exists().where(DesktopMeetingLink.meeting_id == MeetingSession.id).correlate(MeetingSession)
    )
    return (
        select(
            MeetingSession,
            Customer.name.label("customer_name"),
            ProjectObject.name.label("object_name"),
            own_uuid.label("client_uuid"),
            any_link.label("has_link"),
        )
        .outerjoin(Customer, Customer.id == MeetingSession.customer_id)
        .outerjoin(ProjectObject, ProjectObject.id == MeetingSession.object_id)
    )


def _item_fields(row) -> dict:
    m: MeetingSession = row.MeetingSession
    return dict(
        meeting_id=m.id, title=m.title, meeting_topic=m.meeting_topic,
        started_at=m.started_at, ended_at=m.ended_at,
        customer_id=m.customer_id, customer_name=row.customer_name,
        object_id=m.object_id, object_name=row.object_name,
        finalization_status=m.finalization_status or "not_started",
        protocol_ready=bool(m.protocol_markdown), micro_summary=m.micro_summary,
        client_uuid=row.client_uuid, source="desktop" if row.has_link else "web",
    )


@router.get("/library", response_model=list[DesktopLibraryItem])
async def library(
    auth: Device,
    q: str | None = Query(None),
    customer_id: int | None = Query(None),
    object_id: int | None = Query(None),
    limit: int = Query(200, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    """Завершённые встречи сайта (как GET /api/meetings по умолчанию), новые сверху."""
    stmt = (
        _library_select(auth.user.id)
        .where(accessible_meeting_filter(auth.user.id), MeetingSession.is_active == False)  # noqa: E712
        .order_by(MeetingSession.started_at.desc(), MeetingSession.id.desc())
        .limit(limit)
    )
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
    return [DesktopLibraryItem(**_item_fields(r)) for r in rows]


@router.get("/meetings/{meeting_id}/view", response_model=DesktopMeetingView)
async def meeting_view(meeting_id: int, auth: Device, db: AsyncSession = Depends(get_db)):
    """Встреча целиком для просмотра: протокол, реплики, документы."""
    row = (await db.execute(
        _library_select(auth.user.id).where(MeetingSession.id == meeting_id)
    )).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Встреча не найдена")
    if not await user_can_access_meeting(db, auth.user.id, meeting_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Нет доступа к встрече")

    segments = (await db.execute(
        select(TranscriptSegmentRecord)
        .where(TranscriptSegmentRecord.session_id == meeting_id)
        .order_by(TranscriptSegmentRecord.wall_clock.asc())
    )).scalars().all()
    docs = (await db.execute(
        select(MeetingDocumentRecord)
        .where(MeetingDocumentRecord.session_id == meeting_id)
        .order_by(MeetingDocumentRecord.created_at.asc())
    )).scalars().all()

    return DesktopMeetingView(
        **_item_fields(row),
        protocol_markdown=row.MeetingSession.protocol_markdown,
        segments=[
            DesktopSegmentOut(
                text=s.text, speaker_label=s.speaker_label,
                start_time=s.start_time, end_time=s.end_time, wall_clock=s.wall_clock,
            )
            for s in segments
        ],
        documents=[
            DesktopDocumentOut(
                filename=d.filename, doc_type=d.doc_type,
                doc_type_label=DOC_TYPE_LABELS.get(d.doc_type, d.doc_type),
                page_count=d.page_count,
            )
            for d in docs
        ],
    )


@router.get("/projects", response_model=list[DesktopCustomer])
async def projects(auth: Device, db: AsyncSession = Depends(get_db)):
    """Все заказчики с активными объектами (как справочник сайта). Двумя запросами, без N+1."""
    customers = (await db.execute(select(Customer).order_by(Customer.name, Customer.id))).scalars().all()
    objects = (await db.execute(
        select(ProjectObject).where(ProjectObject.is_active == True)  # noqa: E712
        .order_by(ProjectObject.name, ProjectObject.id)
    )).scalars().all()
    by_customer: dict[int, list[DesktopObjectOut]] = {}
    for o in objects:
        by_customer.setdefault(o.customer_id, []).append(
            DesktopObjectOut(id=o.id, name=o.name, address=o.address)
        )
    return [
        DesktopCustomer(id=c.id, name=c.name, objects=by_customer.get(c.id, []))
        for c in customers
    ]
