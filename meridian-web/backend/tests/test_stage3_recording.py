"""Тесты прав записи и мобильного списка (Этап 3).

Доступ/право записи — на rollback-сессии. Поведение комнаты — in-memory.
"""

from app.models.user import User
from app.models.meeting import MeetingSession
from app.models.directory import (
    Customer,
    ProjectObject,
    ObjectAccessGrant,
    MeetingParticipant,
)
from app.services.access import can_record_meeting
from app.services.meeting_room import MeetingRoom, MeetingConnection
from app.api.mobile import mobile_meetings
from app.api.history import meeting_live_state


async def _mobile_list(db, user):
    """Вызов endpoint'а напрямую с явными параметрами (минуя нерезолвнутые Query-дефолты)."""
    return await mobile_meetings(
        status=None, customer_id=None, object_id=None, q=None, only_live=False,
        user=user, db=db,
    )


async def _mk_user(db, email: str) -> User:
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _mk_meeting(db, owner: User, object_id: int | None = None) -> MeetingSession:
    m = MeetingSession(
        user_id=owner.id, created_by_user_id=owner.id,
        is_active=True, status="active", object_id=object_id,
    )
    db.add(m)
    await db.flush()
    await db.refresh(m)
    return m


async def _mk_object_with_grant(db, owner: User, grantee: User, level: str):
    cust = Customer(owner_user_id=owner.id, name="Зак")
    db.add(cust); await db.flush(); await db.refresh(cust)
    obj = ProjectObject(owner_user_id=owner.id, customer_id=cust.id, name="Об")
    db.add(obj); await db.flush(); await db.refresh(obj)
    db.add(ObjectAccessGrant(
        object_id=obj.id, grantee_type="user", grantee_user_id=grantee.id,
        access_level=level, created_by_user_id=owner.id,
    ))
    await db.flush()
    return obj


def _conn(meeting_id, user_id, role, sink, can_record):
    async def send(d):
        sink.append(d)
    return MeetingConnection(meeting_id, user_id, role, send, can_record=can_record)


# --- 1–5: can_record_meeting ---

async def test_can_record_creator(db):
    owner = await _mk_user(db, "rec-owner@test.local")
    m = await _mk_meeting(db, owner)
    assert await can_record_meeting(db, owner.id, m.id) is True


async def test_can_record_participant(db):
    owner = await _mk_user(db, "rec-owner2@test.local")
    member = await _mk_user(db, "rec-part@test.local")
    m = await _mk_meeting(db, owner)
    db.add(MeetingParticipant(meeting_id=m.id, user_id=member.id, role="participant"))
    await db.flush()
    assert await can_record_meeting(db, member.id, m.id) is True


async def test_can_record_viewer_denied(db):
    owner = await _mk_user(db, "rec-owner3@test.local")
    viewer = await _mk_user(db, "rec-viewer@test.local")
    m = await _mk_meeting(db, owner)
    db.add(MeetingParticipant(meeting_id=m.id, user_id=viewer.id, role="viewer"))
    await db.flush()
    assert await can_record_meeting(db, viewer.id, m.id) is False


async def test_can_record_object_edit(db):
    owner = await _mk_user(db, "rec-owner4@test.local")
    editor = await _mk_user(db, "rec-edit@test.local")
    obj = await _mk_object_with_grant(db, owner, editor, "edit")
    m = await _mk_meeting(db, owner, object_id=obj.id)
    assert await can_record_meeting(db, editor.id, m.id) is True


async def test_can_record_object_view_denied(db):
    owner = await _mk_user(db, "rec-owner5@test.local")
    watcher = await _mk_user(db, "rec-view@test.local")
    obj = await _mk_object_with_grant(db, owner, watcher, "view")
    m = await _mk_meeting(db, owner, object_id=obj.id)
    # просмотр есть, запись — нет
    assert await can_record_meeting(db, watcher.id, m.id) is False


# --- 6–7: мобильный список видимости ---

async def test_mobile_list_returns_accessible(db):
    owner = await _mk_user(db, "mob-owner@test.local")
    member = await _mk_user(db, "mob-part@test.local")
    watcher = await _mk_user(db, "mob-obj@test.local")

    m_created = await _mk_meeting(db, owner)
    m_part = await _mk_meeting(db, owner)
    db.add(MeetingParticipant(meeting_id=m_part.id, user_id=member.id, role="participant"))
    obj = await _mk_object_with_grant(db, owner, watcher, "view")
    m_obj = await _mk_meeting(db, owner, object_id=obj.id)
    await db.flush()

    owner_ids = {x.id for x in await _mobile_list(db, owner)}
    member_ids = {x.id for x in await _mobile_list(db, member)}
    watcher_ids = {x.id for x in await _mobile_list(db, watcher)}

    assert m_created.id in owner_ids       # создатель
    assert m_part.id in member_ids         # участник
    assert m_obj.id in watcher_ids         # доступ через объект


async def test_mobile_list_hides_inaccessible(db):
    owner = await _mk_user(db, "mob-owner2@test.local")
    stranger = await _mk_user(db, "mob-stranger@test.local")
    m = await _mk_meeting(db, owner)  # без объекта; stranger не участник
    await db.flush()
    stranger_ids = {x.id for x in await _mobile_list(db, stranger)}
    assert m.id not in stranger_ids


# --- 8: live-state содержит право записи ---

async def test_live_state_has_can_record(db):
    owner = await _mk_user(db, "ls-owner@test.local")
    m = await _mk_meeting(db, owner)
    state = await meeting_live_state(m.id, user=owner, db=db)
    assert "can_current_user_record" in state
    assert state["can_current_user_record"] is True
    assert state["current_user_role"] == "creator"


# --- 9–10: MeetingRoom авторизация записи ---

async def test_room_phone_without_record_cannot_send_audio():
    c = _conn(1, 1, "phone", [], can_record=False)
    assert c.can_send_audio is False
    c2 = _conn(1, 1, "phone", [], can_record=True)
    assert c2.can_send_audio is True


async def test_start_audio_record_permission_denied():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    sink = []
    conn = _conn(1, 99, "phone", sink, can_record=False)
    room.connections[conn.connection_id] = conn
    await room.start_audio(conn.connection_id)
    assert any(d.get("type") == "record_permission_denied" for d in sink)
    assert room.active_audio_source is None  # источник не назначен
