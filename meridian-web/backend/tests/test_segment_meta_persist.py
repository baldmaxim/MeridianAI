# -*- coding: utf-8 -*-
"""Язык, перевод и метка говорящего реплики: запись в БД, поздний UPDATE, чтение в истории."""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.history import get_meeting_detail
from app.core.transcription.models import CommittedSegment
from app.database import Base
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.user import User
from app.services import meeting_room as room_mod
from app.services.meeting_room import MeetingRoom


@pytest_asyncio.fixture
async def maker(monkeypatch):
    """Изолированный in-memory SQLite + патч async_session в meeting_room (прод не трогаем)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
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


async def _room(sm) -> tuple[MeetingRoom, User, int]:
    async with sm() as db:
        owner = User(email="meta@test.local", password_hash="x", role="user", is_active=True)
        db.add(owner)
        await db.flush()
        meeting = MeetingSession(
            user_id=owner.id, created_by_user_id=owner.id, is_active=True, status="active",
        )
        db.add(meeting)
        await db.commit()
        owner_id, meeting_id = owner.id, meeting.id
    room = MeetingRoom(meeting_id=meeting_id, owner_user_id=owner_id, status="active")
    return room, owner, meeting_id


async def _row(sm, segment_id) -> TranscriptSegmentRecord:
    async with sm() as db:
        return (await db.execute(
            select(TranscriptSegmentRecord).where(TranscriptSegmentRecord.segment_id == segment_id)
        )).scalar_one()


async def _drain(room: MeetingRoom) -> None:
    while room._meta_tasks:
        await asyncio.gather(*list(room._meta_tasks))


async def test_persist_writes_language_translation_and_speaker(maker):
    room, _owner, _mid = await _room(maker)
    seg = CommittedSegment(text="Merhaba", language="tr", translation="Здравствуйте",
                           diarized_speaker="s1_speaker_0")
    room.session.committed_segments.append(seg)
    await room._persist_segments(close=False)

    row = await _row(maker, seg.segment_id)
    assert (row.language, row.translation, row.diarized_speaker) == (
        "tr", "Здравствуйте", "s1_speaker_0")


async def test_persist_truncates_long_values_and_keeps_none(maker):
    room, _owner, _mid = await _room(maker)
    long_seg = CommittedSegment(text="a", language="x" * 40, diarized_speaker="y" * 100)
    plain = CommittedSegment(text="б")
    room.session.committed_segments.extend([long_seg, plain])
    await room._persist_segments(close=False)

    row = await _row(maker, long_seg.segment_id)
    assert row.language == "x" * 16 and row.diarized_speaker == "y" * 64
    row = await _row(maker, plain.segment_id)
    assert (row.language, row.translation, row.diarized_speaker) == (None, None, None)


async def test_late_translation_and_speaker_update_saved_row(maker):
    room, _owner, _mid = await _room(maker)
    seg = CommittedSegment(text="Merhaba", language="tr")
    room.session.committed_segments.append(seg)
    await room._persist_segments(close=False)
    assert (await _row(maker, seg.segment_id)).translation is None

    seg.translation = "Здравствуйте"
    room.session._notify_segment_meta(seg)      # как после перевода
    await _drain(room)
    seg.diarized_speaker = "s1_speaker_1"
    room.session._on_segment_speaker(seg, "s1_speaker_1")  # как после on_speaker/speakers_merged
    await _drain(room)

    row = await _row(maker, seg.segment_id)
    assert (row.language, row.translation, row.diarized_speaker) == (
        "tr", "Здравствуйте", "s1_speaker_1")

    seg.diarized_speaker = "s1_speaker_2"        # speakers_merged изменил метку
    room.session._on_segment_speaker(seg, "s1_speaker_2")
    await _drain(room)
    assert (await _row(maker, seg.segment_id)).diarized_speaker == "s1_speaker_2"


async def test_event_before_persist_is_written_by_persist(maker):
    room, _owner, _mid = await _room(maker)
    seg = CommittedSegment(text="Merhaba", language="tr")
    room.session.committed_segments.append(seg)
    seg.translation = "Привет"
    room.session._notify_segment_meta(seg)      # строки ещё нет — UPDATE ничего не ломает
    await _drain(room)
    await room._persist_segments(close=False)
    assert (await _row(maker, seg.segment_id)).translation == "Привет"


async def test_existing_row_from_earlier_session_gets_meta_on_next_persist(maker):
    room, _owner, mid = await _room(maker)
    seg = CommittedSegment(text="Merhaba")
    room.session.committed_segments.append(seg)
    await room._persist_segments(close=False)

    # новая комната той же встречи (рестарт): строка уже в БД, поля у сегмента появились позже
    room2 = MeetingRoom(meeting_id=mid, owner_user_id=room.owner_user_id, status="active")
    seg.language, seg.translation = "en", "Привет"
    room2.session.committed_segments.append(seg)
    await room2._persist_segments(close=False)
    row = await _row(maker, seg.segment_id)
    assert (row.language, row.translation) == ("en", "Привет")


async def test_meeting_detail_returns_meta_fields(maker):
    room, owner, mid = await _room(maker)
    seg = CommittedSegment(text="Merhaba", language="tr", translation="Здравствуйте",
                           diarized_speaker="s1_speaker_0")
    old = CommittedSegment(text="привет")
    room.session.committed_segments.extend([seg, old])
    await room._persist_segments(close=False)

    async with maker() as db:
        detail = await get_meeting_detail(mid, user=owner, db=db)
    by_id = {s.segment_id: s for s in detail.segments}
    got = by_id[seg.segment_id]
    assert (got.language, got.translation, got.diarized_speaker) == (
        "tr", "Здравствуйте", "s1_speaker_0")
    assert by_id[old.segment_id].language is None
    assert by_id[old.segment_id].translation is None
