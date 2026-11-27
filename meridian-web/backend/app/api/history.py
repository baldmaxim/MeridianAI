"""Meeting history API routes."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("meridian.history")

from ..database import get_db
from ..models.user import User
from ..models.meeting import MeetingSession, TranscriptSegmentRecord, MeetingSuggestion, MeetingDocumentRecord
from ..schemas.suggestion import SuggestionCard
from ..models.directory import Customer, ProjectObject, MeetingParticipant
from ..models.document import DocumentRecord
from ..core.context.document_loader import DOC_TYPE_LABELS
from ..schemas.meeting import (
    MeetingListItem,
    MeetingDetailResponse,
    MeetingTitleUpdate,
    MeetingBatchDelete,
    MeetingCreate,
    MeetingUpdate,
    MeetingCreateResponse,
    TranscriptSegmentResponse,
    TranscriptWordResponse,
    MeetingSuggestionResponse,
    MeetingDocumentResponse,
    MeetingAudioOut,
    MeetingAudioPart,
)
from ..schemas.directory import MeetingParticipantResponse
from ..auth.dependencies import get_current_user
from ..services.access import (
    accessible_meeting_filter,
    user_can_access_customer,
    user_can_access_object,
    user_can_access_meeting,
    user_can_access_document,
    can_record_meeting,
)
from ..api.objects import resolve_or_create_customer
from ..services.meeting_audio_links import list_meeting_audio_parts
from ..services.segment_words import assign_batch_words, parse_words_json
from ..models.batch_job import BatchJob
from ..core.batch.term_corrector import effective_transcription
from ..services.meeting_room import compute_live_state
from ..services.protocol_lists import load_protocol_lists
from ..services.meeting_finalize import close_and_request_finalization, request_finalization
from ..schemas.document import MeetingDocumentItem, MeetingDocumentPatch
from ..services.meeting_documents import (
    attach_document,
    detach_document,
    list_meeting_document_items,
    meeting_document_item,
    set_document_inclusion,
)
from ..schemas.finalization import (
    FinalizationStatusResponse,
    MeetingProtocolResponse,
    ProtocolPatch,
)
import json as _json

router = APIRouter()


# --- Валидация привязки заказчик/объект ---


async def _resolve_customer_object(
    db: AsyncSession, user: User, customer_id: int | None, object_id: int | None,
    customer_name: str | None = None,
) -> tuple[int | None, int | None]:
    """Проверяет связку customer/object и доступ пользователя. Возвращает (customer_id, object_id).

    Приоритет резолва заказчика: объект → customer_id → customer_name (найти-или-создать).
    """
    if object_id is not None:
        obj = await db.get(ProjectObject, object_id)
        if obj is None:
            raise HTTPException(422, "Объект не найден")
        if customer_id is not None and obj.customer_id != customer_id:
            raise HTTPException(422, "Объект не принадлежит выбранному заказчику")
        # если заказчик не передан — берём из объекта
        customer_id = obj.customer_id
        if not await user_can_access_object(db, user.id, object_id):
            raise HTTPException(403, "Нет доступа к объекту")
    elif customer_id is not None:
        if await db.get(Customer, customer_id) is None:
            raise HTTPException(422, "Заказчик не найден")
        if not await user_can_access_customer(db, user.id, customer_id):
            raise HTTPException(403, "Нет доступа к заказчику")
    elif customer_name and customer_name.strip():
        customer = await resolve_or_create_customer(db, user.id, customer_name)
        customer_id = customer.id
    return customer_id, object_id


async def _ensure_offer_submission(db: AsyncSession, object_id: int | None, offer_submission: str) -> None:
    """422, если у объекта нет документов этой подачи ("" — корзина «Вне папок подач»)."""
    exists = object_id is not None and await db.scalar(
        select(DocumentRecord.id).where(
            DocumentRecord.object_id == object_id,
            DocumentRecord.offer_submission == offer_submission,
        ).limit(1)
    ) is not None
    if not exists:
        raise HTTPException(422, "Подача не найдена у объекта")


def _is_meeting_owner(meeting: MeetingSession, user: User) -> bool:
    # Общая хронология: встреча не принадлежит пользователю — управлять/удалять
    # может любой авторизованный сотрудник.
    return True


# --- Список встреч (по доступу + фильтры) ---


@router.get("", response_model=list[MeetingListItem])
async def list_meetings(
    customer_id: int | None = Query(None),
    object_id: int | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    include_active: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List meetings the user has access to (created/participant/object grant).

    По умолчанию — только завершённые (is_active == False). include_active=True
    добавляет незавершённые черновики (чтобы запись с телефона не «терялась» на ПК).
    """
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

    stmt = (
        select(
            MeetingSession.id,
            MeetingSession.title,
            MeetingSession.meeting_topic,
            MeetingSession.negotiation_type,
            MeetingSession.started_at,
            MeetingSession.ended_at,
            MeetingSession.recorded_seconds,
            MeetingSession.status,
            MeetingSession.customer_id,
            MeetingSession.object_id,
            MeetingSession.offer_submission,
            MeetingSession.finalization_status,
            MeetingSession.micro_summary,
            MeetingSession.tags_json,
            Customer.name.label("customer_name"),
            ProjectObject.name.label("object_name"),
            seg_count.label("segment_count"),
            sug_count.label("suggestion_count"),
        )
        .outerjoin(Customer, Customer.id == MeetingSession.customer_id)
        .outerjoin(ProjectObject, ProjectObject.id == MeetingSession.object_id)
        .where(
            accessible_meeting_filter(user.id),
        )
        .order_by(MeetingSession.started_at.desc())
    )

    if not include_active:
        stmt = stmt.where(MeetingSession.is_active == False)
    if customer_id is not None:
        stmt = stmt.where(MeetingSession.customer_id == customer_id)
    if object_id is not None:
        stmt = stmt.where(MeetingSession.object_id == object_id)
    if status:
        stmt = stmt.where(MeetingSession.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            func.coalesce(MeetingSession.title, "").ilike(like)
            | func.coalesce(MeetingSession.meeting_topic, "").ilike(like)
        )

    rows = (await db.execute(stmt)).all()
    # Live-признак записи берём из in-memory реестра комнат (тот же процесс) — без миграции.
    from ..services.meeting_room import room_registry
    return [
        MeetingListItem(
            id=r.id,
            title=r.title,
            meeting_topic=r.meeting_topic,
            negotiation_type=r.negotiation_type,
            started_at=r.started_at,
            ended_at=r.ended_at,
            recorded_seconds=r.recorded_seconds,
            status=r.status,
            is_recording=bool(
                (room := room_registry.get_room(r.id)) and room.session.is_listening
            ),
            customer_id=r.customer_id,
            object_id=r.object_id,
            customer_name=r.customer_name,
            object_name=r.object_name,
            offer_submission=r.offer_submission,
            finalization_status=r.finalization_status,
            micro_summary=r.micro_summary,
            tags=_json.loads(r.tags_json) if r.tags_json else [],
            segment_count=r.segment_count or 0,
            suggestion_count=r.suggestion_count or 0,
        )
        for r in rows
    ]


# --- Создание встречи (REST draft, WS подхватит активную) ---


@router.post("", response_model=MeetingCreateResponse)
async def create_meeting(
    data: MeetingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать встречу-draft (active) с привязкой к заказчику/объекту.

    WS при подключении подхватит самую свежую активную встречу (без изменений в WS).
    """
    customer_id, object_id = await _resolve_customer_object(
        db, user, data.customer_id, data.object_id, data.customer_name
    )
    if data.offer_submission is not None:
        await _ensure_offer_submission(db, object_id, data.offer_submission)

    # Этап 9: новая встреча получает default AI-профиль пользователя
    from ..services.ai_settings import get_or_create_default_profile
    default_profile = await get_or_create_default_profile(db, user.id)

    meeting = MeetingSession(
        user_id=user.id,
        created_by_user_id=user.id,
        is_active=True,
        status="active",
        customer_id=customer_id,
        object_id=object_id,
        offer_submission=data.offer_submission,
        title=data.title,
        meeting_topic=data.meeting_topic,
        meeting_notes=data.meeting_notes,
        negotiation_type=data.negotiation_type,
        meeting_role=data.meeting_role,
        opponent_weaknesses=data.opponent_weaknesses,
        ai_settings_profile_id=default_profile.id,
    )
    db.add(meeting)
    await db.flush()

    db.add(MeetingParticipant(meeting_id=meeting.id, user_id=user.id, role="owner"))
    await db.flush()
    await db.refresh(meeting)
    return meeting


@router.patch("/{meeting_id}", response_model=MeetingCreateResponse)
async def update_meeting(
    meeting_id: int,
    data: MeetingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Обновить встречу (заказчик/объект/статус/контекст) с проверкой доступа."""
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")

    updates = data.model_dump(exclude_unset=True)
    # подача КП: явное значение (в т.ч. null — сброс) или сброс при смене объекта
    object_changed = False
    # привязка заказчик/объект проверяется только если что-то из них меняется
    if "customer_id" in updates or "object_id" in updates or "customer_name" in updates:
        new_object = updates.get("object_id", meeting.object_id)
        cust_name = updates.get("customer_name")
        # приоритет: явный customer_id → текстовый customer_name → текущий заказчик встречи
        if "customer_id" in updates:
            new_customer = updates["customer_id"]
        elif cust_name and cust_name.strip():
            new_customer = None  # пусть резолвится из customer_name (найти-или-создать)
        else:
            new_customer = meeting.customer_id
        new_customer, new_object = await _resolve_customer_object(
            db, user, new_customer, new_object, cust_name
        )
        object_changed = new_object != meeting.object_id
        if "offer_submission" in updates and updates["offer_submission"] is not None:
            await _ensure_offer_submission(db, new_object, updates["offer_submission"])
        meeting.customer_id = new_customer
        meeting.object_id = new_object
        updates.pop("customer_id", None)
        updates.pop("object_id", None)
        updates.pop("customer_name", None)
    elif updates.get("offer_submission") is not None:
        await _ensure_offer_submission(db, meeting.object_id, updates["offer_submission"])
    if object_changed and "offer_submission" not in updates:
        updates["offer_submission"] = None

    for key, value in updates.items():
        setattr(meeting, key, value)
    await db.flush()
    await db.refresh(meeting)
    return meeting


# --- Участники встречи ---


@router.get("/{meeting_id}/participants", response_model=list[MeetingParticipantResponse])
async def list_participants(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    result = await db.execute(
        select(MeetingParticipant, User)
        .join(User, User.id == MeetingParticipant.user_id)
        .where(MeetingParticipant.meeting_id == meeting_id)
        .order_by(MeetingParticipant.created_at)
    )
    return [
        MeetingParticipantResponse(
            id=mp.id,
            meeting_id=mp.meeting_id,
            user_id=mp.user_id,
            role=mp.role,
            created_at=mp.created_at,
            email=u.email,
            display_name=u.display_name,
        )
        for mp, u in result.all()
    ]


@router.post("/{meeting_id}/participants/{user_id}", response_model=MeetingParticipantResponse)
async def add_participant(
    meeting_id: int,
    user_id: int,
    role: str = Query("participant"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    if not _is_meeting_owner(meeting, user):
        raise HTTPException(403, "Только создатель встречи может управлять участниками")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Пользователь не найден")

    existing = await db.execute(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.user_id == user_id,
        )
    )
    mp = existing.scalar_one_or_none()
    if mp is None:
        mp = MeetingParticipant(meeting_id=meeting_id, user_id=user_id, role=role)
        db.add(mp)
        await db.flush()
        await db.refresh(mp)

    return MeetingParticipantResponse(
        id=mp.id,
        meeting_id=mp.meeting_id,
        user_id=mp.user_id,
        role=mp.role,
        created_at=mp.created_at,
        email=target.email,
        display_name=target.display_name,
    )


@router.delete("/{meeting_id}/participants/{user_id}")
async def remove_participant(
    meeting_id: int,
    user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    if not _is_meeting_owner(meeting, user):
        raise HTTPException(403, "Только создатель встречи может управлять участниками")
    result = await db.execute(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.user_id == user_id,
        )
    )
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(404, "Участник не найден")
    await db.delete(mp)
    await db.flush()
    return {"ok": True}


@router.post("/batch/delete")
async def batch_delete_meetings(
    data: MeetingBatchDelete,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple meetings at once (общая хронология — любые запрошенные)."""
    logger.info(f"[batch-delete] user={user.id} ids={data.ids}")
    if not data.ids:
        return {"ok": True, "deleted": 0}

    result = await db.execute(
        select(MeetingSession).where(MeetingSession.id.in_(data.ids))
    )
    meetings = result.scalars().all()
    logger.info(f"[batch-delete] found {len(meetings)} meetings to delete (requested {len(data.ids)})")

    # Закрыть живые комнаты удаляемых встреч (оповестить устройства + свернуть движок)
    from app.services.meeting_room import room_registry
    for m in meetings:
        room = room_registry.get_room(m.id)
        if room:
            await room.terminate("deleted")
            room_registry.remove(m.id)

    for m in meetings:
        await db.delete(m)

    await db.flush()
    logger.info(f"[batch-delete] flush done, deleted={len(meetings)}")
    return {"ok": True, "deleted": len(meetings)}


# --- Этап 4: документы встречи ---


async def _get_meeting_or_404(db: AsyncSession, user: User, meeting_id: int) -> MeetingSession:
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    return meeting


@router.get("/{meeting_id}/documents", response_model=list[MeetingDocumentItem])
async def list_meeting_documents(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Прикреплённые документы встречи + документы её заказчика/объекта (source: meeting|customer|object)."""
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return []
    return await list_meeting_document_items(db, meeting, include_not_ready=True)


@router.post("/{meeting_id}/documents/{document_id}", response_model=MeetingDocumentItem)
async def attach_meeting_document(
    meeting_id: int,
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = await _get_meeting_or_404(db, user, meeting_id)
    doc = await db.get(DocumentRecord, document_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    if not await user_can_access_document(db, user.id, document_id):
        raise HTTPException(403, "Нет доступа к документу")
    # объект встречи и документа не должны конфликтовать
    if meeting.object_id and doc.object_id and meeting.object_id != doc.object_id:
        raise HTTPException(422, "Документ привязан к другому объекту, чем встреча")

    md = await attach_document(db, meeting, doc, user.id)
    return await meeting_document_item(db, meeting, md, doc)


@router.patch("/{meeting_id}/documents/{document_id}", response_model=MeetingDocumentItem)
async def patch_meeting_document(
    meeting_id: int,
    document_id: int,
    data: MeetingDocumentPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    meeting = await db.get(MeetingSession, meeting_id)
    found = None
    if meeting is not None:
        found = await set_document_inclusion(
            db, meeting, document_id, included=data.included, priority=data.priority,
        )
    if found is None:
        raise HTTPException(404, "Документ не прикреплён к встрече")
    md, doc = found
    return await meeting_document_item(db, meeting, md, doc)


@router.delete("/{meeting_id}/documents/{document_id}")
async def detach_meeting_document(
    meeting_id: int,
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None or not await detach_document(db, meeting, document_id):
        raise HTTPException(404, "Документ не прикреплён к встрече")
    return {"ok": True}


# --- Этап 6: история подсказок (карточки) ---


@router.get("/{meeting_id}/suggestions", response_model=list[SuggestionCard])
async def list_meeting_suggestions(
    meeting_id: int,
    source_mode: str | None = Query(None),
    type: str | None = Query(None),
    needs_user_check: bool | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    stmt = select(MeetingSuggestion).where(MeetingSuggestion.session_id == meeting_id)
    if source_mode:
        stmt = stmt.where(MeetingSuggestion.source_mode == source_mode)
    if type:
        stmt = stmt.where(MeetingSuggestion.suggestion_type == type)
    if needs_user_check is not None:
        stmt = stmt.where(MeetingSuggestion.needs_user_check == needs_user_check)
    stmt = stmt.order_by(MeetingSuggestion.created_at)
    rows = (await db.execute(stmt)).scalars().all()

    cards: list[SuggestionCard] = []
    for r in rows:
        if r.card_json:
            try:
                cards.append(SuggestionCard(**_json.loads(r.card_json)))
                continue
            except (ValueError, TypeError):
                pass
        # legacy-строки → собрать карточку из старых полей
        cards.append(SuggestionCard(
            type=r.suggestion_type or "clarify",
            title=r.title or "",
            text=r.text,
            why=r.why or "",
            confidence=(r.confidence or 50) / 100.0,
            needs_user_check=r.needs_user_check,
            trigger=r.trigger,
            source_mode=r.source_mode or ("auto" if r.is_auto else "manual"),
            created_at=r.created_at,
        ))
    return cards


# --- Этап 5: финализация встречи ---


@router.post("/{meeting_id}/finalize", response_model=FinalizationStatusResponse)
async def finalize_meeting_endpoint(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завершить встречу (если ещё live) и поставить формирование протокола в очередь."""
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для завершения встречи")
    await close_and_request_finalization(db, meeting)
    await db.flush()
    return FinalizationStatusResponse(
        meeting_id=meeting.id, status=meeting.finalization_status,
        error=meeting.finalization_error, finalized_at=meeting.finalized_at,
        has_protocol=bool(meeting.protocol_markdown),
    )


@router.post("/{meeting_id}/finalization/retry", response_model=FinalizationStatusResponse)
async def retry_finalization(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для повторной финализации")
    if meeting.finalization_status in ("queued", "running"):
        raise HTTPException(409, "Финализация уже выполняется")
    await request_finalization(db, meeting_id)
    await db.flush()
    return FinalizationStatusResponse(
        meeting_id=meeting.id, status=meeting.finalization_status,
        error=meeting.finalization_error, finalized_at=meeting.finalized_at,
        has_protocol=bool(meeting.protocol_markdown),
    )


@router.get("/{meeting_id}/finalization-status", response_model=FinalizationStatusResponse)
async def get_finalization_status(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    return FinalizationStatusResponse(
        meeting_id=meeting.id, status=meeting.finalization_status,
        error=meeting.finalization_error, finalized_at=meeting.finalized_at,
        has_protocol=bool(meeting.protocol_markdown),
    )


@router.get("/{meeting_id}/protocol", response_model=MeetingProtocolResponse)
async def get_meeting_protocol(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")

    lists = await load_protocol_lists(db, meeting_id)

    return MeetingProtocolResponse(
        meeting_id=meeting.id,
        finalization_status=meeting.finalization_status,
        title=meeting.title,
        micro_summary=meeting.micro_summary,
        tags=_json.loads(meeting.tags_json) if meeting.tags_json else [],
        protocol_markdown=meeting.protocol_markdown,
        protocol_json=_json.loads(meeting.protocol_json) if meeting.protocol_json else None,
        decisions=lists.decisions,
        action_items=lists.action_items,
        risks=lists.risks,
        open_questions=lists.open_questions,
    )


@router.patch("/{meeting_id}/protocol", response_model=MeetingProtocolResponse)
async def patch_meeting_protocol(
    meeting_id: int,
    data: ProtocolPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для редактирования протокола")
    if data.title is not None:
        meeting.title = data.title[:255]
    if data.micro_summary is not None:
        meeting.micro_summary = data.micro_summary
    if data.tags is not None:
        meeting.tags_json = _json.dumps(data.tags, ensure_ascii=False)
    if data.protocol_markdown is not None:
        meeting.protocol_markdown = data.protocol_markdown
    await db.flush()
    return await get_meeting_protocol(meeting_id, user=user, db=db)


@router.get("/{meeting_id}/live-state")
async def meeting_live_state(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Текущее live-состояние встречи: подключения, активный источник аудио, доступ."""
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    allowed = await user_can_access_meeting(db, user.id, meeting_id)
    if not allowed:
        raise HTTPException(status_code=403, detail="Нет доступа к встрече")

    return await compute_live_state(db, meeting, user.id)


@router.get("/{meeting_id}/audio", response_model=MeetingAudioOut)
async def get_meeting_audio(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Части записи встречи (presigned GET) для проигрывания; нет записи — 404 audio_not_found."""
    if await db.get(MeetingSession, meeting_id) is None:
        raise HTTPException(status_code=404, detail="Встреча не найдена")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(status_code=403, detail="Нет доступа к встрече")
    parts = await list_meeting_audio_parts(db, meeting_id)
    if not parts:
        raise HTTPException(status_code=404, detail="audio_not_found")
    return MeetingAudioOut(parts=[
        MeetingAudioPart(url=p.url, source=p.source, expires_in=p.expires_in, name=p.name)
        for p in parts
    ])


async def _batch_words_for_segments(
    db: AsyncSession, meeting_id: int, records: list[TranscriptSegmentRecord],
) -> dict[str, list[dict]]:
    """Слова батча по segment_id для сегментов batch_finalized без words_json.

    Только если у встречи ровно одно распознавание; любой сбой — warning и пустой результат.
    """
    targets = [r for r in records if r.origin == "batch_finalized" and not parse_words_json(r.words_json)]
    if not targets:
        return {}
    try:
        jobs = (await db.execute(
            select(BatchJob)
            .where(BatchJob.meeting_id == meeting_id,
                   BatchJob.transcription_json.isnot(None),
                   BatchJob.transcription_json != "")
            .limit(2)
        )).scalars().all()
        if len(jobs) != 1:
            return {}
        data = effective_transcription(jobs[0])
        words = data.get("words") if isinstance(data, dict) else None
        if not isinstance(words, list) or not words:
            return {}
        assigned = assign_batch_words([(r.start_time, r.end_time) for r in targets], words)
        return {r.segment_id: w for r, w in zip(targets, assigned) if w}
    except Exception as exc:  # noqa: BLE001 — слова необязательны, деталь встречи не должна падать
        logger.warning("[meeting-words] meeting=%s: слова батча не разобраны (%s)", meeting_id, type(exc).__name__)
        return {}


@router.get("/{meeting_id}", response_model=MeetingDetailResponse)
async def get_meeting_detail(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full meeting detail with segments and suggestions."""
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(status_code=403, detail="Нет доступа к встрече")

    # Имена заказчика/объекта
    customer_name = None
    object_name = None
    if meeting.customer_id:
        c = await db.get(Customer, meeting.customer_id)
        customer_name = c.name if c else None
    if meeting.object_id:
        o = await db.get(ProjectObject, meeting.object_id)
        object_name = o.name if o else None

    # Load segments
    seg_result = await db.execute(
        select(TranscriptSegmentRecord)
        .where(TranscriptSegmentRecord.session_id == meeting_id)
        .order_by(TranscriptSegmentRecord.wall_clock.asc())
    )
    seg_records = list(seg_result.scalars().all())
    batch_words = await _batch_words_for_segments(db, meeting_id, seg_records)
    segments = []
    for rec in seg_records:
        seg = TranscriptSegmentResponse.model_validate(rec)
        words = parse_words_json(rec.words_json) or batch_words.get(rec.segment_id)
        if words:
            seg.words = [TranscriptWordResponse(**w) for w in words]
        segments.append(seg)

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
        app_notes=meeting.app_notes,
        started_at=meeting.started_at,
        ended_at=meeting.ended_at,
        recorded_seconds=meeting.recorded_seconds,
        status=meeting.status,
        customer_id=meeting.customer_id,
        object_id=meeting.object_id,
        customer_name=customer_name,
        object_name=object_name,
        offer_submission=meeting.offer_submission,
        micro_summary=meeting.micro_summary,
        tags_json=meeting.tags_json,
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
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(status_code=403, detail="Нет доступа к встрече")

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
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(status_code=403, detail="Нет доступа к встрече")

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
    """Delete a meeting and all related data (только создатель/владелец)."""
    logger.info(f"[delete] user={user.id} meeting_id={meeting_id}")
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        logger.warning(f"[delete] meeting {meeting_id} not found")
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(status_code=403, detail="Нет доступа к встрече")
    if not _is_meeting_owner(meeting, user):
        raise HTTPException(status_code=403, detail="Удалять встречу может только создатель")

    # Закрыть живую комнату: оповестить устройства (meeting_closed) и свернуть движок
    from app.services.meeting_room import room_registry
    room = room_registry.get_room(meeting_id)
    if room:
        await room.terminate("deleted")
        room_registry.remove(meeting_id)

    logger.info(f"[delete] deleting meeting id={meeting.id} title={meeting.title!r}")
    await db.delete(meeting)
    await db.flush()
    logger.info(f"[delete] flush done for meeting {meeting_id}")
    return {"ok": True}
