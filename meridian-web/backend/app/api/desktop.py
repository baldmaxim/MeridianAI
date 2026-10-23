# -*- coding: utf-8 -*-
"""Ручки десктоп-приложения записи встреч.

Приложение на ПК пишет встречу локально, распознаёт её на месте и при появлении сети
отправляет сюда. Любой запрос приложение может повторить после обрыва сети, поэтому все
записи идемпотентны (см. services/desktop_sync).

Вход — по паролю с выдачей токена устройства (в базе только его хэш, как у OCR-агентов); дальше
приложение ходит с `Authorization: Bearer <токен>`. Ручки списка и отзыва устройств — для сайта
(обычный JWT пользователя).
"""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..config import get_settings
from ..database import get_db
from ..models.document import DocumentRecord
from ..models.file import FileRecord
from ..models.meeting import MeetingSession
from ..models.user import User
from ..ratelimit import limiter
from ..schemas.desktop import (
    AudioConfirmResponse,
    AudioUploadRequest,
    AudioUploadResponse,
    DesktopDeviceOut,
    DesktopDocumentConfirmRequest,
    DesktopDocumentPatchRequest,
    DesktopDocumentUploadRequest,
    DesktopLoginRequest,
    DesktopLoginResponse,
    DesktopMeResponse,
    DesktopMeetingItem,
    DesktopUserOut,
    MeetingPatchRequest,
    MeetingPatchResponse,
    MeetingUpsertRequest,
    MeetingUpsertResponse,
    SegmentsRequest,
    SegmentsResponse,
)
from ..schemas.document import (
    DocumentConfirmResponse,
    DocumentUploadSessionRequest,
    DocumentUploadSessionResponse,
    MeetingDocumentItem,
)
from ..schemas.finalization import FinalizationStatusResponse
from ..schemas.meeting_ask import MeetingAskRequest, MeetingAskResponse
from ..schemas.speaker_role import SpeakerRoleOut, SpeakerRolePut
from ..services import desktop_sync as sync
from ..services import document_storage
from ..services.meeting_documents import (
    attach_document,
    list_meeting_document_items,
    meeting_document_item,
    set_document_inclusion,
)
from ..services import s3
from ..services import speaker_roles as sr
from ..services.meeting_ask import MeetingAskError, answer_question
from ..services.meeting_room import room_registry
from ..services.audit import audit, client_ip, hmac_email
from ..services.desktop_devices import (
    DesktopAuth,
    authenticate_device,
    check_credentials,
    enroll_device,
    get_user_device,
    list_devices,
    revoke_device,
    touch_device,
)
from .batch import ALLOWED_EXTENSIONS, MAX_FILE_SIZE
from .documents import confirm_s3_document_upload, create_s3_document_upload
from .history import _resolve_customer_object

logger = logging.getLogger("meridian.desktop")

router = APIRouter()


async def current_desktop_device(
    db: AsyncSession = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
) -> DesktopAuth:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    auth = await authenticate_device(db, token)
    if auth is None:
        # В лог — факт, но не токен.
        logger.warning("неопознанное устройство десктоп-приложения")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Токен устройства не принят")
    await touch_device(db, auth.device)
    return auth


Device = Annotated[DesktopAuth, Depends(current_desktop_device)]


def _user_out(user: User) -> DesktopUserOut:
    return DesktopUserOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role)


async def _linked(db: AsyncSession, auth: DesktopAuth, meeting_id: int):
    found = await sync.get_linked_meeting(db, auth.user.id, meeting_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Встреча не найдена")
    return found


def _finalization_response(meeting: MeetingSession) -> FinalizationStatusResponse:
    return FinalizationStatusResponse(
        meeting_id=meeting.id, status=meeting.finalization_status,
        error=meeting.finalization_error, finalized_at=meeting.finalized_at,
        has_protocol=bool(meeting.protocol_markdown),
    )


# ── вход и устройство ──────────────────────────────────────────────────────


@router.post("/login", response_model=DesktopLoginResponse)
@limiter.limit("5/minute")
async def desktop_login(request: Request, data: DesktopLoginRequest, db: AsyncSession = Depends(get_db)):
    """Войти по паролю и получить токен устройства. Токен показывается один раз."""
    ip = client_ip(request)
    email_hmac = hmac_email(data.email)
    user, reason = await check_credentials(db, data.email, data.password)
    if reason is not None:
        await audit("desktop_login_failed", actor_user_id=user.id if user else None,
                    ip=ip, email_hmac=email_hmac, reason=reason)
        if reason == "inactive":
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    device, token = await enroll_device(db, user.id, data.device_name, data.platform, data.app_version)
    await db.commit()
    await audit("desktop_login_success", actor_user_id=user.id, ip=ip,
                email_hmac=email_hmac, device_id=device.id)
    return DesktopLoginResponse(device_token=token, device_id=device.id, user=_user_out(user))


@router.get("/me", response_model=DesktopMeResponse)
async def desktop_me(auth: Device):
    return DesktopMeResponse(user=_user_out(auth.user), device=DesktopDeviceOut.model_validate(auth.device))


@router.post("/logout")
async def desktop_logout(request: Request, auth: Device, db: AsyncSession = Depends(get_db)):
    await revoke_device(db, auth.device)
    await db.commit()
    await audit("desktop_device_revoked", actor_user_id=auth.user.id, ip=client_ip(request),
                device_id=auth.device.id, via="logout")
    return {"ok": True}


# ── устройства для сайта (JWT пользователя) ─────────────────────────────────


@router.get("/devices", response_model=list[DesktopDeviceOut])
async def devices_list(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await list_devices(db, user.id)


@router.delete("/devices/{device_id}")
async def devices_revoke(
    device_id: int, request: Request,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    device = await get_user_device(db, user.id, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Устройство не найдено")
    await revoke_device(db, device)
    await db.commit()
    await audit("desktop_device_revoked", actor_user_id=user.id, ip=client_ip(request),
                device_id=device_id, via="site")
    return {"ok": True}


# ── встречи ───────────────────────────────────────────────────────────────


async def _refresh_live_room(meeting: MeetingSession) -> None:
    """Если по встрече идёт живая комната — подсказки сразу видят новый контекст. Нет комнаты — ничего."""
    room = room_registry.get_room(meeting.id)
    if room is None:
        return
    try:
        await room.refresh_context(meeting)
    except Exception:
        logger.exception("Не удалось обновить контекст живой комнаты встречи %s", meeting.id)


@router.post("/meetings", response_model=MeetingUpsertResponse)
async def meetings_upsert(data: MeetingUpsertRequest, auth: Device, db: AsyncSession = Depends(get_db)):
    """Создать встречу или вернуть уже созданную с тем же client_uuid (title/ended_at обновятся)."""
    client_uuid = str(data.client_uuid)
    customer_id, object_id = data.customer_id, data.object_id
    # Заказчика и объект проверяем только при создании: повтор их не меняет.
    if await sync.get_link(db, auth.user.id, client_uuid) is None:
        customer_id, object_id = await _resolve_customer_object(
            db, auth.user, data.customer_id, data.object_id
        )
    meeting, created = await sync.upsert_meeting(
        db, auth.user.id, auth.device.id, client_uuid,
        title=data.title, started_at=data.started_at, ended_at=data.ended_at,
        capture_mode=data.capture_mode, customer_id=customer_id, object_id=object_id,
        negotiation_type=data.negotiation_type, key_terms=data.key_terms,
        opponent_weaknesses=data.opponent_weaknesses,
    )
    await db.commit()
    context_given = any(
        v is not None for v in (data.negotiation_type, data.key_terms, data.opponent_weaknesses)
    )
    if context_given and not created:
        await _refresh_live_room(meeting)
    return MeetingUpsertResponse(meeting_id=meeting.id, created=created)


@router.get("/meetings", response_model=list[DesktopMeetingItem])
async def meetings_list(auth: Device, db: AsyncSession = Depends(get_db)):
    """Встречи, принятые от приложения этим пользователем."""
    return [
        DesktopMeetingItem(
            meeting_id=m.id, client_uuid=link.client_uuid, title=m.title, started_at=m.started_at,
            finalization_status=m.finalization_status or "not_started",
            protocol_ready=bool(m.protocol_markdown),
        )
        for m, link in await sync.list_meetings(db, auth.user.id)
    ]


@router.put("/meetings/{meeting_id}/segments", response_model=SegmentsResponse)
async def meetings_segments(
    meeting_id: int, data: SegmentsRequest, auth: Device, db: AsyncSession = Depends(get_db),
):
    """Принять пачку сегментов транскрипта (upsert по client_segment_id)."""
    meeting, link = await _linked(db, auth, meeting_id)
    segments = [
        sync.SegmentIn(
            client_segment_id=s.client_segment_id, text=s.text, start_time=s.start_time,
            end_time=s.end_time, wall_clock=s.wall_clock, channel=s.channel,
            speaker_label=s.speaker_label,
        )
        for s in data.segments
    ]
    try:
        created, updated = await sync.upsert_segments(db, meeting, link, segments)
    except sync.DesktopMeetingClosedError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))
    await db.commit()
    return SegmentsResponse(created=created, updated=updated)


@router.patch("/meetings/{meeting_id}", response_model=MeetingPatchResponse)
async def meetings_patch(
    meeting_id: int, data: MeetingPatchRequest, auth: Device, db: AsyncSession = Depends(get_db),
):
    """Название, конец встречи, заметки пользователя (app_notes, списком целиком) и контекст встречи."""
    meeting, _ = await _linked(db, auth, meeting_id)
    if data.title is not None and data.title.strip():
        meeting.title = data.title.strip()[:255]
    if data.ended_at is not None:
        meeting.ended_at = sync.to_naive_utc(data.ended_at)
    if data.notes is not None:
        meeting.app_notes = sync.format_notes([(n.at_seconds, n.text) for n in data.notes])
    context_changed = sync.apply_context(
        meeting, negotiation_type=data.negotiation_type, key_terms=data.key_terms,
        opponent_weaknesses=data.opponent_weaknesses,
    )
    await db.commit()
    if context_changed:
        await _refresh_live_room(meeting)
    return MeetingPatchResponse(meeting_id=meeting.id, title=meeting.title, ended_at=meeting.ended_at)


@router.put("/meetings/{meeting_id}/speaker-roles/{speaker_label}", response_model=list[SpeakerRoleOut])
async def meetings_speaker_role(
    meeting_id: int, speaker_label: str, data: SpeakerRolePut, auth: Device,
    db: AsyncSession = Depends(get_db),
):
    """Назначить голосу («Голос 1») сторону self/opponent или очистить (side=null). Работает и после финализации."""
    await _linked(db, auth, meeting_id)
    await sr.upsert_role(db, meeting_id, speaker_label, side=data.side,
                         display_name=data.display_name, assigned_by_user_id=auth.user.id)
    await db.commit()
    await sr.sync_room_role(meeting_id, speaker_label, data.side, data.display_name)
    return await sr.list_roles(db, meeting_id)


@router.post("/meetings/{meeting_id}/finalize", response_model=FinalizationStatusResponse)
async def meetings_finalize(meeting_id: int, auth: Device, db: AsyncSession = Depends(get_db)):
    """Завершить встречу и поставить протокол в очередь. Повтор отдаёт текущий статус."""
    meeting, _ = await _linked(db, auth, meeting_id)
    await sync.finalize(db, meeting)
    await db.commit()
    return _finalization_response(meeting)


@router.post("/meetings/{meeting_id}/ask", response_model=MeetingAskResponse)
@limiter.limit("20/minute")
async def meetings_ask(
    request: Request, meeting_id: int, data: MeetingAskRequest, auth: Device,
    db: AsyncSession = Depends(get_db),
):
    """Вопрос по встрече: ответ по документам, прошлым встречам, транскрипту и заметкам.

    Работает и после финализации.
    """
    meeting, _ = await _linked(db, auth, meeting_id)
    try:
        return await answer_question(db, auth.user, meeting, data.question)
    except MeetingAskError as e:
        raise HTTPException(e.status_code, e.message)


# ── аудио ─────────────────────────────────────────────────────────────────


@router.post("/meetings/{meeting_id}/audio-upload", response_model=AudioUploadResponse)
async def meetings_audio_upload(
    meeting_id: int, data: AudioUploadRequest, auth: Device, db: AsyncSession = Depends(get_db),
):
    """Presigned PUT для аудио встречи. Только хранение: обработка аудио не запускается."""
    if not get_settings().s3_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="S3-хранилище не настроено")
    await _linked(db, auth, meeting_id)
    ext = Path(data.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Формат {ext} не поддерживается. Допустимые: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    if data.size > MAX_FILE_SIZE:
        raise HTTPException(400, f"Файл слишком большой (макс. {MAX_FILE_SIZE // 1024 // 1024}MB)")

    # Канал держим в имени файла («mic_…», «system_…»): отдельной колонки в files нет. Имя же
    # служит ключом идемпотентности — повтор запроса отдаёт ту же запись, а не плодит новые.
    name = f"{data.channel}_{Path(data.filename).name}"[:500]
    rec = (await db.execute(
        select(FileRecord).where(
            FileRecord.user_id == auth.user.id, FileRecord.meeting_id == meeting_id,
            FileRecord.purpose == "meeting_audio", FileRecord.original_name == name,
            FileRecord.status.in_(("pending", "active")),
        ).order_by(FileRecord.id)
    )).scalars().first()
    if rec is not None and rec.status == "active":
        return AudioUploadResponse(file_id=rec.id, upload_url=None, status="active")
    if rec is None:
        rec = FileRecord(
            user_id=auth.user.id,
            object_key=s3.object_key(auth.user.id, "meeting_audio", data.filename),
            original_name=name,
            size=data.size,
            purpose="meeting_audio",
            status="pending",
            meeting_id=meeting_id,
        )
        db.add(rec)
        await db.flush()
    upload_url = s3.presign_put(rec.object_key)
    await db.commit()
    return AudioUploadResponse(file_id=rec.id, upload_url=upload_url, status="pending")


@router.post("/meetings/{meeting_id}/audio-confirm/{file_id}", response_model=AudioConfirmResponse)
async def meetings_audio_confirm(
    meeting_id: int, file_id: int, auth: Device, db: AsyncSession = Depends(get_db),
):
    """Проверить объект в S3 и активировать запись. Повтор на активной — без обращения к S3."""
    await _linked(db, auth, meeting_id)
    rec = (await db.execute(
        select(FileRecord).where(
            FileRecord.id == file_id, FileRecord.user_id == auth.user.id,
            FileRecord.meeting_id == meeting_id, FileRecord.purpose == "meeting_audio",
            FileRecord.status.in_(("pending", "active")),
        )
    )).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    if rec.status != "active":
        meta = await s3.head_object(rec.object_key)
        if not meta:
            raise HTTPException(400, "Объект не загружен в хранилище")
        rec.status = "active"
        rec.size = meta["size"]
        rec.mime = meta.get("content_type")
        await db.commit()
    return AudioConfirmResponse(file_id=rec.id, status=rec.status, size=rec.size)


# ── документы встречи ───────────────────────────────────────────────────────
# Те же внутренности, что у сайта (api/documents.py, services/meeting_documents.py). Мультипарта
# для десктопа нет: без S3 приложение получит 503 и повторит позже.


@router.post("/documents/upload-session", response_model=DocumentUploadSessionResponse)
async def documents_upload_session(
    data: DesktopDocumentUploadRequest, response: Response, auth: Device,
    db: AsyncSession = Depends(get_db),
):
    """Presigned PUT для документа. Заказчик и объект берутся из встречи."""
    # в ответе presigned URL с подписью — не кэшируем
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    if not document_storage.is_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="S3-хранилище не настроено")
    meeting, _ = await _linked(db, auth, data.meeting_id)
    request = DocumentUploadSessionRequest(
        filename=data.filename, content_type=data.mime_type, size_bytes=data.size,
        customer_id=meeting.customer_id, object_id=meeting.object_id,
    )
    return await create_s3_document_upload(db, auth.user, request, meeting_id=meeting.id)


@router.post("/documents/{document_id}/confirm", response_model=DocumentConfirmResponse)
async def documents_confirm(
    document_id: int, data: DesktopDocumentConfirmRequest, auth: Device,
    db: AsyncSession = Depends(get_db),
):
    """Подтвердить загрузку, запустить обработку и прикрепить документ к встрече. Повтор безопасен."""
    meeting, _ = await _linked(db, auth, data.meeting_id)
    doc = await db.get(DocumentRecord, document_id)
    if doc is None or doc.created_by_user_id != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    if doc.status == "pending":
        doc = await confirm_s3_document_upload(db, auth.user, document_id, meeting_id=meeting.id)
    # дальше повтор: обработка уже запущена (или завершена) — заново её не ставим
    await attach_document(db, meeting, doc, auth.user.id)
    await db.commit()
    return DocumentConfirmResponse(document_id=doc.id, status=doc.status)


@router.get("/meetings/{meeting_id}/documents", response_model=list[MeetingDocumentItem])
async def meetings_documents(meeting_id: int, auth: Device, db: AsyncSession = Depends(get_db)):
    """Документы встречи: прикреплённые и унаследованные от заказчика/объекта (source), с типом и тегами."""
    meeting, _ = await _linked(db, auth, meeting_id)
    return await list_meeting_document_items(db, meeting)


@router.patch("/meetings/{meeting_id}/documents/{document_id}", response_model=MeetingDocumentItem)
async def meetings_document_patch(
    meeting_id: int, document_id: int, data: DesktopDocumentPatchRequest, auth: Device,
    db: AsyncSession = Depends(get_db),
):
    """Включить/выключить документ в контексте встречи (унаследованному создаётся своя строка)."""
    meeting, _ = await _linked(db, auth, meeting_id)
    found = await set_document_inclusion(
        db, meeting, document_id, included=data.included, priority=None,
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Документ не прикреплён к встрече")
    md, doc = found
    item = await meeting_document_item(db, meeting, md, doc)
    await db.commit()
    return item
