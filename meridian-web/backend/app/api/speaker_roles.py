"""API persisted-ролей спикеров встречи (source of truth для дерева общения).

GET — user_can_access_meeting. PUT — can_record_meeting (creator/participant/edit/manage).
View-only менять не может. PUT синхронизирует роль в live-комнату, если она открыта.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..auth.dependencies import get_current_user
from ..services.access import user_can_access_meeting, can_record_meeting
from ..services import speaker_roles as sr
from ..services.meeting_room import room_registry
from ..schemas.speaker_role import SpeakerRoleOut, SpeakerRolePut

logger = logging.getLogger("meridian.speaker_roles.api")

router = APIRouter()


@router.get("/{meeting_id}/speaker-roles", response_model=list[SpeakerRoleOut])
async def get_speaker_roles(meeting_id: int, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    return await sr.list_roles(db, meeting_id)


@router.put("/{meeting_id}/speaker-roles/{speaker_label}", response_model=list[SpeakerRoleOut])
async def put_speaker_role(meeting_id: int, speaker_label: str, body: SpeakerRolePut,
                           user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения ролей")

    await sr.upsert_role(db, meeting_id, speaker_label, side=body.side,
                         display_name=body.display_name, assigned_by_user_id=user.id)
    await db.commit()

    # синхронизировать live-комнату (cache) + уведомить устройства
    room = room_registry.get_room(meeting_id)
    if room:
        norm = sr.normalize_side(body.side)
        if norm is None:
            room.session.speaker_roles.pop(speaker_label, None)
        else:
            room.session.speaker_roles[speaker_label] = norm
        try:
            await room.broadcast({"type": "speaker_roles_updated", "roles": room.session.speaker_roles})
        except Exception:
            pass

    return await sr.list_roles(db, meeting_id)
