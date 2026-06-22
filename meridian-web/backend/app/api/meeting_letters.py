"""API прикреплённых писем PayHub к встрече (ручной выбор писем в контекст).

Хранится в meeting_context_sources (source_type='letter', source_id=NULL): снапшот письма
в metadata_json. Пути под /api: /meetings/{id}/letters. Доступ — как у rag-folders встречи:
просмотр — user_can_access_meeting, изменение — can_record_meeting.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.context_source import MeetingContextSource
from ..models.meeting import MeetingSession
from ..models.user import User
from ..schemas.letters import MeetingLetterAttach, MeetingLetterOut, MeetingLetterUpdate
from ..services import letters_context as letters
from ..services.access import can_record_meeting, user_can_access_meeting
from ..services.meeting_room import room_registry

logger = logging.getLogger("meridian.rag_letters")

router = APIRouter()


async def _notify_updated(meeting_id: int) -> None:
    room = room_registry.get_room(meeting_id)
    if room:
        try:
            await room.broadcast({"type": "meeting_context_sources_updated", "meeting_id": meeting_id})
        except Exception:
            pass


def _get_src_or_404(src: MeetingContextSource | None, meeting_id: int) -> MeetingContextSource:
    if not src or src.meeting_id != meeting_id or src.source_type != letters.SOURCE_TYPE_LETTER:
        raise HTTPException(404, "Письмо не подключено")
    return src


@router.get("/{meeting_id}/letters", response_model=list[MeetingLetterOut])
async def list_meeting_letters(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    return await letters.list_attached_letters(db, meeting_id)


@router.post("/{meeting_id}/letters", response_model=MeetingLetterOut)
async def attach_meeting_letter(
    meeting_id: int,
    data: MeetingLetterAttach,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(MeetingSession, meeting_id) is None:
        raise HTTPException(404, "Встреча не найдена")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения контекста встречи")
    try:
        out = await letters.attach_letter_to_meeting(db, meeting_id, data, user.id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    await _notify_updated(meeting_id)
    return out


@router.patch("/{meeting_id}/letters/{source_id}", response_model=MeetingLetterOut)
async def update_meeting_letter(
    meeting_id: int,
    source_id: int,
    data: MeetingLetterUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения контекста встречи")
    src = _get_src_or_404(await db.get(MeetingContextSource, source_id), meeting_id)
    try:
        out = await letters.update_attached_letter(db, src, included=data.included, priority=data.priority)
    except ValueError as e:
        raise HTTPException(422, str(e))
    await _notify_updated(meeting_id)
    return out


@router.delete("/{meeting_id}/letters/{source_id}")
async def detach_meeting_letter(
    meeting_id: int,
    source_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения контекста встречи")
    src = _get_src_or_404(await db.get(MeetingContextSource, source_id), meeting_id)
    await letters.detach_letter_from_meeting(db, src)
    await _notify_updated(meeting_id)
    return {"ok": True}
