"""API segment-level коррекций диаризации (Этап 8).

GET — user_can_access_meeting. PUT/DELETE/bulk — can_record_meeting.
После мутаций broadcast нового события `speaker_corrections_updated` (WS event names
прежних не меняем — это новое событие).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..auth.dependencies import get_current_user
from ..services.access import user_can_access_meeting, can_record_meeting
from ..services import speaker_corrections as sc
from ..services.meeting_room import room_registry
from ..schemas.speaker_correction import (
    SpeakerSegmentCorrectionOut, SpeakerSegmentCorrectionPut, SpeakerSegmentCorrectionsBulkPut,
)

logger = logging.getLogger("meridian.speaker_corrections.api")

router = APIRouter()


async def _notify(db: AsyncSession, meeting_id: int) -> None:
    room = room_registry.get_room(meeting_id)
    if not room:
        return
    try:
        # обновить live-кэш комнаты, чтобы prompt-транскрипт сразу учитывал коррекции
        room.session.set_speaker_segment_corrections(
            await sc.get_segment_corrections_cache(db, meeting_id)
        )
        rows = await sc.get_segment_corrections_out(db, meeting_id)
        await room.broadcast({
            "type": "speaker_corrections_updated",
            "meeting_id": meeting_id,
            "corrections": [r.model_dump(mode="json") for r in rows],
        })
    except Exception:
        pass


@router.get("/{meeting_id}/speaker-corrections", response_model=list[SpeakerSegmentCorrectionOut])
async def get_speaker_corrections(
    meeting_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    return await sc.get_segment_corrections_out(db, meeting_id)


@router.put("/{meeting_id}/speaker-corrections/{segment_key}", response_model=list[SpeakerSegmentCorrectionOut])
async def put_speaker_correction(
    meeting_id: int, segment_key: str, body: SpeakerSegmentCorrectionPut,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения коррекций")
    try:
        await sc.upsert_segment_correction(
            db, meeting_id, segment_key,
            original_speaker_label=body.original_speaker_label,
            corrected_speaker_label=body.corrected_speaker_label,
            side=body.side, note=body.note, user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    await db.commit()
    await _notify(db, meeting_id)
    return await sc.get_segment_corrections_out(db, meeting_id)


@router.delete("/{meeting_id}/speaker-corrections/{segment_key}")
async def delete_speaker_correction(
    meeting_id: int, segment_key: str,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения коррекций")
    try:
        await sc.delete_segment_correction(db, meeting_id, segment_key)
    except ValueError as e:
        raise HTTPException(422, str(e))
    await db.commit()
    await _notify(db, meeting_id)
    return {"ok": True}


@router.post("/{meeting_id}/speaker-corrections/bulk", response_model=list[SpeakerSegmentCorrectionOut])
async def bulk_put_speaker_corrections(
    meeting_id: int, body: SpeakerSegmentCorrectionsBulkPut,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения коррекций")
    try:
        out = await sc.bulk_upsert_segment_corrections(db, meeting_id, body.items, user_id=user.id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    await db.commit()
    await _notify(db, meeting_id)
    return out
