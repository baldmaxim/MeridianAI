"""API предпросмотра Context Pack (Этап 6).

GET /api/meetings/{meeting_id}/context-preview — показывает, какие блоки контекста
попадут в подсказки (не вызывает LLM, не стартует встречу, не требует websocket-комнаты).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.meeting import MeetingSession
from ..auth.dependencies import get_current_user
from ..services.access import user_can_access_meeting
from ..services.context_pack import assemble_static_context_pack_for_meeting
from ..schemas.context_preview import ContextPackPreviewOut

logger = logging.getLogger("meridian.context_preview")

router = APIRouter()

_ALLOWED_MODES = {"auto", "manual", "strengthen", "preview"}


@router.get("/meetings/{meeting_id}/context-preview", response_model=ContextPackPreviewOut)
async def context_preview(
    meeting_id: int,
    mode: str = Query("manual"),
    q: str | None = Query(None),
    preview_chars_per_block: int = Query(1200, ge=0, le=20000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if mode not in _ALLOWED_MODES:
        raise HTTPException(422, "Недопустимый режим предпросмотра")
    if await db.get(MeetingSession, meeting_id) is None:
        raise HTTPException(404, "Встреча не найдена")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")

    pack = await assemble_static_context_pack_for_meeting(
        db, meeting_id=meeting_id, viewer_user_id=user.id, mode=mode, query_text=q or "",
    )
    preview = pack.to_preview(preview_chars_per_block)
    preview["meeting_id"] = meeting_id
    return preview
