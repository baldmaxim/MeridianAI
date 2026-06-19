"""Multi-channel WAV export API (Этап 9.4).

Диагностический многоканальный WAV из текущего in-memory ingest-окна. Только чтение:
не создаёт meeting, не вызывает STT, не мутирует room/ingest, не пишет disk/БД/S3.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.meeting import MeetingSession
from ..config import get_settings
from ..services.access import can_record_meeting
from ..services.meeting_room import room_registry
from ..services.multi_channel_wav import MultiChannelExportError
from ..services.multi_channel_export_service import (
    prepare_multi_channel_audio, build_prepared_wav, PreparedMultiChannelAudio,
)
from ..schemas.multi_channel_export import MultiChannelExportRequest, MultiChannelExportPlanOut

router = APIRouter()
logger = logging.getLogger("meridian.wav_export")

_ERROR_STATUS = {
    "EXPORT_DISABLED": 503,
    "NO_TRACKS": 422,
    "TRACK_NOT_FOUND": 422,
    "TOO_MANY_CHANNELS": 422,
    "INVALID_WINDOW": 422,
    "INVALID_OFFSET": 422,
    "SAMPLE_RATE_MISMATCH": 422,
    "NO_COMMON_WINDOW": 422,
    "NO_COMMON_WINDOW_RANGE": 422,
    "NO_AUDIO_DATA": 409,
    "DURATION_LIMIT": 413,
    "BYTE_LIMIT": 413,
}


def _http_from_export_error(e: MultiChannelExportError) -> HTTPException:
    return HTTPException(status_code=_ERROR_STATUS.get(e.code, 422),
                         detail={"code": e.code, "message": str(e)})


async def _prepare(meeting_id: int, req: MultiChannelExportRequest, user: User,
                   db: AsyncSession):
    """Общая подготовка: доступ → live room → окно → immutable snapshot → plan.

    Все обращения к ingest синхронны (без await между ними) — snapshot атомарен к ingest.
    Возвращает (snapshot, plan).
    """
    settings = get_settings()
    if not settings.multi_channel_export_enabled:
        raise HTTPException(503, detail={"code": "EXPORT_DISABLED",
                                         "message": "Экспорт многоканального WAV выключен"})

    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        raise HTTPException(404, detail={"code": "MEETING_NOT_FOUND", "message": "Встреча не найдена"})

    # raw audio доступен только при праве записи (не viewer-only)
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Нет доступа к записи встречи"})

    room = room_registry.get_room(meeting_id)
    if room is None or not getattr(room, "ingest", None):
        raise HTTPException(409, detail={"code": "NO_ROOM", "message": "Активная сессия встречи не найдена"})

    # снимок/план через общий helper (синхронно → атомарно к ingest)
    try:
        return prepare_multi_channel_audio(
            room=room, request=req, settings=settings,
            meeting_id=meeting_id, created_at=datetime.now(timezone.utc),
        )
    except MultiChannelExportError as e:
        raise _http_from_export_error(e)


@router.post("/{meeting_id}/multi-source/export-plan", response_model=MultiChannelExportPlanOut)
async def export_plan(meeting_id: int, req: MultiChannelExportRequest,
                      user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    prepared: PreparedMultiChannelAudio = await _prepare(meeting_id, req, user, db)
    return JSONResponse(content=prepared.manifest)


@router.post("/{meeting_id}/multi-source/wav")
async def export_wav(meeting_id: int, req: MultiChannelExportRequest,
                     user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    prepared = await _prepare(meeting_id, req, user, db)
    plan = prepared.plan
    # тяжёлая сборка PCM вне event loop; размер уже ограничен config
    wav_bytes = await build_prepared_wav(prepared)
    filename = f"meridian-meeting-{meeting_id}-multichannel.wav"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(wav_bytes)),
        "X-Meridian-Channels": str(plan.channel_count),
        "X-Meridian-Duration-Ms": str(plan.duration_ms),
        "X-Meridian-Start-Server-Ms": str(plan.start_index * plan.frame_ms),
        "X-Meridian-End-Server-Ms": str(plan.end_index * plan.frame_ms),
    }
    return Response(content=wav_bytes, media_type="audio/wav", headers=headers)
