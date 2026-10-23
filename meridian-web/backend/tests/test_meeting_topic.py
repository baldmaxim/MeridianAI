"""Тема встречи: ручное редактирование через PATCH и нормализация."""

from app.api.history import update_meeting
from app.models.meeting import MeetingSession
from app.models.user import User
from app.schemas.meeting import MAX_MEETING_TOPIC_LENGTH, MeetingUpdate, normalize_meeting_topic


async def _mk(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    m = MeetingSession(user_id=u.id, created_by_user_id=u.id, is_active=True, status="active")
    db.add(m)
    await db.flush()
    await db.refresh(m)
    return u, m


def test_normalize_topic():
    assert normalize_meeting_topic(None) is None
    assert normalize_meeting_topic("   ") is None
    assert normalize_meeting_topic("  Кровля  ") == "Кровля"
    assert len(normalize_meeting_topic("я" * 2000)) == MAX_MEETING_TOPIC_LENGTH


async def test_patch_topic_set_and_clear(db):
    user, meeting = await _mk(db, "topic-patch@test.local")

    await update_meeting(meeting.id, MeetingUpdate(meeting_topic="  Гидроизоляция кровли  "), user=user, db=db)
    assert meeting.meeting_topic == "Гидроизоляция кровли"

    await update_meeting(meeting.id, MeetingUpdate(meeting_topic="   "), user=user, db=db)
    assert meeting.meeting_topic is None


async def test_patch_without_topic_keeps_it(db):
    user, meeting = await _mk(db, "topic-keep@test.local")
    await update_meeting(meeting.id, MeetingUpdate(meeting_topic="Тема"), user=user, db=db)
    await update_meeting(meeting.id, MeetingUpdate(title="Название"), user=user, db=db)
    assert meeting.meeting_topic == "Тема"
    assert meeting.title == "Название"
