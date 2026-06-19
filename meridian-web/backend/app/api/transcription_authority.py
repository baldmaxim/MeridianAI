"""API авторитетного источника транскрипта (Этап 9.8).

Просмотр state/transcript — user_can_access_meeting. Promote/fallback — can_record_meeting.
Promote требует активной live multi-channel сессии (room в памяти). Всё по умолчанию
недоступно (rollout 0% + allowlist). Авто-promote отсутствует.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.meeting import MeetingSession
from ..auth.dependencies import get_current_user
from ..services.access import user_can_access_meeting, can_record_meeting
from ..services.meeting_room import room_registry
from ..services.transcription_authority_controller import (
    TranscriptionAuthorityController, build_authoritative_from_db,
)
from ..schemas.transcription_authority import (
    TranscriptionAuthorityStateOut, PromoteRequest, FallbackRequest,
    AuthoritativeTranscriptOut,
)

logger = logging.getLogger("meridian.transcription_authority.api")

router = APIRouter()


async def _require_access(db: AsyncSession, user_id: int, meeting_id: int) -> None:
    if not await user_can_access_meeting(db, user_id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")


async def _require_edit(db: AsyncSession, user_id: int, meeting_id: int) -> None:
    if not await can_record_meeting(db, user_id, meeting_id):
        raise HTTPException(403, "Недостаточно прав")


async def _noop(_event) -> None:
    return None


async def _ephemeral_controller(db: AsyncSession, meeting_id: int) -> TranscriptionAuthorityController:
    """Контроллер без live-room (read/manual fallback вне активной сессии)."""
    meeting = await db.get(MeetingSession, meeting_id)
    owner = (meeting.created_by_user_id or meeting.user_id) if meeting else None
    ctrl = TranscriptionAuthorityController(
        meeting_id=meeting_id, owner_user_id=owner,
        get_session=lambda: None, get_live=lambda: None,
        get_reconciliation_summary=lambda: None, get_channel_clock_quality=lambda: {},
        broadcast=_noop)
    await ctrl.load()
    return ctrl


@router.get("/{meeting_id}/transcription-authority/state", response_model=TranscriptionAuthorityStateOut)
async def get_state(meeting_id: int, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    await _require_access(db, user.id, meeting_id)
    room = room_registry.get_room(meeting_id)
    if room:
        return room.cutover.state_dict()
    ctrl = await _ephemeral_controller(db, meeting_id)
    return ctrl.state_dict()


@router.post("/{meeting_id}/transcription-authority/promote", response_model=TranscriptionAuthorityStateOut)
async def promote(meeting_id: int, payload: PromoteRequest = PromoteRequest(),
                  user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_edit(db, user.id, meeting_id)
    room = room_registry.get_room(meeting_id)
    if not room:
        raise HTTPException(409, "Нет активной сессии встречи")
    result = await room.cutover.promote(
        by_user_id=user.id, reason=payload.reason or "manual_promote", force=payload.force)
    if not result.get("ok"):
        raise HTTPException(409, detail={"code": result.get("code"), "message": result.get("message"),
                                         "quality": result.get("quality")})
    return result["state"]


@router.post("/{meeting_id}/transcription-authority/fallback", response_model=TranscriptionAuthorityStateOut)
async def fallback(meeting_id: int, payload: FallbackRequest = FallbackRequest(),
                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_edit(db, user.id, meeting_id)
    room = room_registry.get_room(meeting_id)
    if room:
        result = await room.cutover.fallback(
            by_user_id=user.id, reason=payload.reason or "manual_fallback", automatic=False)
    else:
        ctrl = await _ephemeral_controller(db, meeting_id)
        result = await ctrl.fallback(by_user_id=user.id,
                                     reason=payload.reason or "manual_fallback", automatic=False)
    if not result.get("ok"):
        raise HTTPException(409, detail={"code": result.get("code"), "message": result.get("message")})
    return result["state"]


@router.get("/{meeting_id}/transcription-authority/transcript", response_model=AuthoritativeTranscriptOut)
async def get_transcript(meeting_id: int, max_segments: int = 2000,
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_access(db, user.id, meeting_id)
    transcript = await build_authoritative_from_db(db, meeting_id)
    if transcript is None:
        return AuthoritativeTranscriptOut(
            meeting_id=meeting_id, available=False, epochs_count=0, sources_used=[],
            segment_count=0, truncated=False, segments=[])
    data = transcript.to_dict(max_segments=max(1, min(5000, max_segments)))
    return AuthoritativeTranscriptOut(
        meeting_id=meeting_id, available=True, epochs_count=data["epochs_count"],
        sources_used=data["sources_used"], segment_count=data["segment_count"],
        truncated=data["truncated"], segments=data["segments"])
