"""«Спросить» по встрече для сайта (JWT пользователя). Десктоп-вариант — в api/desktop.py."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.meeting import MeetingSession
from ..models.user import User
from ..ratelimit import limiter
from ..schemas.meeting_ask import MeetingAskRequest, MeetingAskResponse
from ..services.access import user_can_access_meeting
from ..services.meeting_ask import MeetingAskError, answer_question

router = APIRouter()


@router.post("/{meeting_id}/ask", response_model=MeetingAskResponse)
@limiter.limit("20/minute")
async def ask_meeting(
    request: Request, meeting_id: int, data: MeetingAskRequest,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Вопрос по встрече: ответ по документам, прошлым встречам, транскрипту и заметкам."""
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Встреча не найдена")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    try:
        return await answer_question(db, user, meeting, data.question)
    except MeetingAskError as e:
        raise HTTPException(e.status_code, e.message)
