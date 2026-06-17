"""Тесты persisted-ролей спикеров и их связи с деревом общения.

Сервис/эндпоинты — на rollback-сессии. Room — на изолированном SQLite.
"""

import pytest
from datetime import datetime

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.user import User
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.directory import MeetingParticipant
from app.models.meeting_conversation import MeetingConversationTopic, MeetingSpeakerRole
from app.services import speaker_roles as srsvc
from app.services.conversation_tree import ConversationTreeService
from app.api.speaker_roles import get_speaker_roles, put_speaker_role
from app.schemas.speaker_role import SpeakerRolePut


async def _mk_user(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u); await db.flush(); await db.refresh(u)
    return u


async def _mk_meeting(db, owner):
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=True,
                       status="active", started_at=datetime(2026, 1, 1, 10, 0))
    db.add(m); await db.flush(); await db.refresh(m)
    return m


async def _add_segment(db, meeting_id, label, text, idx):
    from datetime import timedelta
    db.add(TranscriptSegmentRecord(
        session_id=meeting_id, segment_id=f"s{meeting_id}_{idx}", text=text,
        start_time=float(idx), end_time=float(idx) + 1,
        wall_clock=datetime(2026, 1, 1, 10, 0) + timedelta(seconds=idx),
        speaker_id="spk", speaker_label=label, origin="live_committed", word_count=len(text.split())))
    await db.flush()


# ---------- 1: роль персистится в БД ----------

async def test_role_persists(db):
    owner = await _mk_user(db, "sr1@test.local")
    m = await _mk_meeting(db, owner)
    role = await srsvc.upsert_role(db, m.id, "Иван", side="self", assigned_by_user_id=owner.id)
    assert role is not None and role.side == "self"
    got = await srsvc.get_roles_map(db, m.id)
    assert got == {"Иван": "self"}


# ---------- нормализация our→self, unknown→очистка ----------

async def test_normalize_and_clear(db):
    owner = await _mk_user(db, "sr2@test.local")
    m = await _mk_meeting(db, owner)
    r = await srsvc.upsert_role(db, m.id, "Пётр", side="our")  # our → self
    assert r.side == "self"
    cleared = await srsvc.upsert_role(db, m.id, "Пётр", side="unknown")  # очистка
    assert cleared is None
    assert await srsvc.get_roles_map(db, m.id) == {}


# ---------- 2: роли загружаются при пересоздании комнаты ----------

@pytest_asyncio.fixture
async def sqlite_sm(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    import app.services.meeting_room as mr
    monkeypatch.setattr(mr, "async_session", sm)
    try:
        yield sm
    finally:
        await engine.dispose()


async def test_roles_load_on_room_recreate(sqlite_sm, monkeypatch):
    from app.services.meeting_room import MeetingRoom
    # заглушки внешних зависимостей create()
    import app.services.meeting_room as mr

    async def _noop_keys():
        return {}

    async def _settings(_owner):
        return {"llm_model": "x", "temperature": 0.7, "stt_provider": "deepgram"}

    async def _snapshot(_db, _mid):
        return {"conversation_tree_enabled": True}

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(mr, "load_api_keys", _noop_keys)
    monkeypatch.setattr(mr, "load_user_settings", _settings)
    monkeypatch.setattr(mr, "snapshot_for_meeting", _snapshot)
    monkeypatch.setattr(mr, "load_default_role", _none)

    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db, "sr3@test.local")
        m = await _mk_meeting(db, owner)
        await srsvc.upsert_role(db, m.id, "Иван", side="self")
        await srsvc.upsert_role(db, m.id, "Заказчик", side="opponent")
        await db.commit()
        mid = m.id

    room = await MeetingRoom.create(mid)
    assert room.session.speaker_roles == {"Иван": "self", "Заказчик": "opponent"}


# ---------- 3: rebuild использует persisted-роли ----------

async def test_rebuild_uses_persisted_roles(db):
    owner = await _mk_user(db, "sr4@test.local")
    m = await _mk_meeting(db, owner)
    await _add_segment(db, m.id, "Иван", "Обсудим сроки сдачи", 0)
    await _add_segment(db, m.id, "Заказчик", "Сроки нас не устраивают", 1)
    await srsvc.upsert_role(db, m.id, "Иван", side="self")
    await srsvc.upsert_role(db, m.id, "Заказчик", side="opponent")
    # rebuild без явных ролей → берёт из БД
    tree = await ConversationTreeService().rebuild_from_segments(db, m.id)
    assert len(tree.topics) == 1
    t = tree.topics[0]
    assert t.normalized_key == "deadlines"
    assert t.our_summary and t.opponent_summary


# ---------- 4: view-only не может PUT ----------

async def test_put_open_to_everyone(db):
    # Общая модель: любой авторизованный может назначить роль спикера.
    owner = await _mk_user(db, "sr5a@test.local")
    other = await _mk_user(db, "sr5b@test.local")
    m = await _mk_meeting(db, owner)
    res = await put_speaker_role(m.id, "Иван", SpeakerRolePut(side="self"), user=other, db=db)
    assert res is not None


# ---------- 5: GET требует доступа ----------

async def test_get_open_to_everyone(db):
    owner = await _mk_user(db, "sr6a@test.local")
    stranger = await _mk_user(db, "sr6b@test.local")
    m = await _mk_meeting(db, owner)
    await srsvc.upsert_role(db, m.id, "Иван", side="self")
    rows = await get_speaker_roles(m.id, user=owner, db=db)
    assert len(rows) == 1
    # общая хронология: посторонний тоже читает роли
    rows2 = await get_speaker_roles(m.id, user=stranger, db=db)
    assert len(rows2) == 1


# ---------- 5b: participant может PUT ----------

async def test_participant_can_put(db):
    owner = await _mk_user(db, "sr7a@test.local")
    editor = await _mk_user(db, "sr7b@test.local")
    m = await _mk_meeting(db, owner)
    db.add(MeetingParticipant(meeting_id=m.id, user_id=editor.id, role="participant"))
    await db.flush()
    rows = await put_speaker_role(m.id, "Иван", SpeakerRolePut(side="opponent"), user=editor, db=db)
    assert any(r.speaker_label == "Иван" and r.side == "opponent" for r in rows)


# ---------- 6: get_tree отдаёт unassigned_speakers ----------

async def test_unassigned_speakers_stats(db):
    owner = await _mk_user(db, "sr8@test.local")
    m = await _mk_meeting(db, owner)
    await _add_segment(db, m.id, "Иван", "Цена обсуждается", 0)
    await _add_segment(db, m.id, "Заказчик", "Дорого", 1)
    await srsvc.upsert_role(db, m.id, "Иван", side="self")  # назначен; Заказчик — нет
    tree = await ConversationTreeService().get_tree(db, m.id)
    assert "Заказчик" in tree.unassigned_speakers
    assert "Иван" not in tree.unassigned_speakers
