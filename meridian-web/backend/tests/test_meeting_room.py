"""Тесты MeetingRoom и доступа к live-комнате (Этап 2).

Доступ (1–4) проверяется через user_can_access_meeting на rollback-сессии.
Поведение комнаты (5–8) тестируется in-memory (без БД).
Финализация по meeting_id (9) — на изолированном in-memory SQLite (не трогает прод).
"""

import asyncio

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.user import User
from app.models.meeting import MeetingSession
from app.models.directory import (
    Customer,
    ProjectObject,
    ObjectAccessGrant,
    MeetingParticipant,
)
from app.services.access import user_can_access_meeting
from app.services import meeting_room as room_mod
from app.services.meeting_room import MeetingRoom, MeetingConnection


# ---------- helpers ----------

async def _mk_user(db, email: str) -> User:
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _mk_meeting(db, owner: User, object_id: int | None = None) -> MeetingSession:
    m = MeetingSession(
        user_id=owner.id,
        created_by_user_id=owner.id,
        is_active=True,
        status="active",
        object_id=object_id,
    )
    db.add(m)
    await db.flush()
    await db.refresh(m)
    return m


def _make_conn(room_id, user_id, role, sink: list):
    async def send(data):
        sink.append(data)
    return MeetingConnection(room_id, user_id, role, send)


# ---------- 1–4: доступ к комнате ----------

async def test_creator_can_access_room(db):
    owner = await _mk_user(db, "room-owner@test.local")
    m = await _mk_meeting(db, owner)
    assert await user_can_access_meeting(db, owner.id, m.id) is True


async def test_participant_can_access_room(db):
    owner = await _mk_user(db, "room-owner2@test.local")
    member = await _mk_user(db, "room-part@test.local")
    m = await _mk_meeting(db, owner)
    db.add(MeetingParticipant(meeting_id=m.id, user_id=member.id, role="participant"))
    await db.flush()
    assert await user_can_access_meeting(db, member.id, m.id) is True


async def test_object_access_can_access_room(db):
    owner = await _mk_user(db, "room-owner3@test.local")
    other = await _mk_user(db, "room-obj@test.local")
    cust = Customer(owner_user_id=owner.id, name="Зак")
    db.add(cust); await db.flush(); await db.refresh(cust)
    obj = ProjectObject(owner_user_id=owner.id, customer_id=cust.id, name="Об")
    db.add(obj); await db.flush(); await db.refresh(obj)
    db.add(ObjectAccessGrant(
        object_id=obj.id, grantee_type="user", grantee_user_id=other.id,
        access_level="view", created_by_user_id=owner.id,
    ))
    m = await _mk_meeting(db, owner, object_id=obj.id)
    await db.flush()
    assert await user_can_access_meeting(db, other.id, m.id) is True


async def test_stranger_cannot_access_room(db):
    owner = await _mk_user(db, "room-owner4@test.local")
    stranger = await _mk_user(db, "room-stranger@test.local")
    m = await _mk_meeting(db, owner)  # без object_id → только создатель/участники
    assert await user_can_access_meeting(db, stranger.id, m.id) is False


# ---------- 5–8: поведение комнаты (in-memory) ----------

async def test_two_connections_join_same_room():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    a, b = [], []
    await room.add_connection(_make_conn(1, 1, "desktop", a))
    await room.add_connection(_make_conn(1, 2, "viewer", b))
    assert len(room.connections) == 2


async def test_broadcast_reaches_desktop_and_viewer():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    a, b = [], []
    ca = _make_conn(1, 1, "desktop", a)
    cb = _make_conn(1, 2, "viewer", b)
    room.connections[ca.connection_id] = ca
    room.connections[cb.connection_id] = cb
    await room.broadcast({"type": "committed_transcript", "text": "hi"})
    assert any(d.get("type") == "committed_transcript" for d in a)
    assert any(d.get("type") == "committed_transcript" for d in b)


async def test_only_active_source_audio_accepted():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    ca = _make_conn(1, 1, "desktop", [])
    cb = _make_conn(1, 2, "desktop", [])
    room.connections[ca.connection_id] = ca
    room.connections[cb.connection_id] = cb
    # эмулируем активную запись без реального STT
    room.session.is_listening = True
    room.session.audio_queue = asyncio.Queue()
    room.set_active_audio_source(ca.connection_id)

    await room.handle_audio_frame(cb.connection_id, b"\x00\x01")  # не источник → игнор
    assert room.session.audio_queue.qsize() == 0
    await room.handle_audio_frame(ca.connection_id, b"\x00\x01")  # источник → принято
    assert room.session.audio_queue.qsize() == 1


async def test_disconnect_one_does_not_finalize():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    ca = _make_conn(1, 1, "desktop", [])
    cb = _make_conn(1, 2, "viewer", [])
    room.connections[ca.connection_id] = ca
    room.connections[cb.connection_id] = cb
    room.set_active_audio_source(ca.connection_id)

    await room.remove_connection(ca.connection_id)  # ушёл активный источник
    assert room.active_audio_source is None          # источник очищен
    assert room.closed is False                      # но встреча НЕ завершена
    assert cb.connection_id in room.connections      # второе соединение живо


# ---------- 9: финализация по meeting_id (изолированный SQLite) ----------

@pytest_asyncio.fixture
async def sqlite_sessionmaker(monkeypatch):
    """Изолированный in-memory SQLite + патч async_session в meeting_room (не трогает прод)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(room_mod, "async_session", sm)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(room_mod, "save_meeting_to_local", _noop)

    try:
        yield sm
    finally:
        await engine.dispose()


async def test_finalize_meeting_by_meeting_id(sqlite_sessionmaker):
    sm = sqlite_sessionmaker
    # подготовить пользователя + встречу
    async with sm() as db:
        owner = User(email="fin-owner@test.local", password_hash="x", role="user", is_active=True)
        db.add(owner)
        await db.flush()
        meeting = MeetingSession(
            user_id=owner.id, created_by_user_id=owner.id, is_active=True, status="active",
        )
        db.add(meeting)
        await db.commit()
        owner_id, meeting_id = owner.id, meeting.id

    room = MeetingRoom(meeting_id=meeting_id, owner_user_id=owner_id, status="active")
    owner_conn = _make_conn(meeting_id, owner_id, "desktop", [])
    room.connections[owner_conn.connection_id] = owner_conn

    await room.finalize_meeting(owner_conn.connection_id)

    assert room.closed is True
    assert room.status == "finalized"
    async with sm() as db:
        m = await db.get(MeetingSession, meeting_id)
        assert m.status == "finalized"
        assert m.is_active is False
