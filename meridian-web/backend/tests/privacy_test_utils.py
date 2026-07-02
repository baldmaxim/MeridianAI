"""Общие хелперы для privacy-тестов (Этап 25). SQLite commit-движок + билдеры данных встречи."""

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base


def make_sqlite_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False})

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _rec):  # pragma: no cover
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine
from app.models.user import User
from app.models.meeting import (
    MeetingSession, TranscriptSegmentRecord, MeetingSuggestion, MeetingDocumentRecord,
)
from app.models.document import DocumentRecord, DocumentChunk
from app.models.file import FileRecord
from app.models.job import Job


@pytest_asyncio.fixture
async def commit_db():
    engine = make_sqlite_engine()
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as s:
            yield s
    finally:
        await engine.dispose()


async def mk_user(db, email, role="user"):
    u = User(email=email, password_hash="x", role=role, is_active=True)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def mk_meeting(db, owner, **kw):
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=False,
                       status="finalized", **kw)
    db.add(m)
    await db.flush()
    await db.refresh(m)
    return m


async def add_transcript(db, meeting, text="цена договора пять миллионов рублей", speaker="SM_0"):
    import datetime as _dt
    s = TranscriptSegmentRecord(
        session_id=meeting.id, segment_id=f"s{meeting.id}_{speaker}"[:12], text=text,
        start_time=0.0, end_time=1.0, wall_clock=_dt.datetime.utcnow(),
        origin="live_committed", speaker_label=speaker)
    db.add(s)
    await db.flush()
    return s


async def add_suggestion(db, meeting):
    s = MeetingSuggestion(session_id=meeting.id, text="Зафиксируйте цену письменно",
                          suggestion_type="priority", title="Фиксация", is_auto=True)
    db.add(s)
    await db.flush()
    return s


async def add_document(db, owner, meeting, *, s3_key="documents/abc123.pdf", shared_meeting=None):
    doc = DocumentRecord(owner_user_id=owner.id, created_by_user_id=owner.id,
                         original_name="СекретныйДоговор.pdf", file_ext=".pdf", status="ready",
                         s3_key=s3_key, file_id=None)
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text="секретный текст чанка"))
    db.add(MeetingDocumentRecord(session_id=meeting.id, document_id=doc.id, included=True, priority=100))
    if shared_meeting is not None:
        db.add(MeetingDocumentRecord(session_id=shared_meeting.id, document_id=doc.id,
                                     included=True, priority=100))
    await db.flush()
    return doc


async def add_meeting_audio(db, owner, meeting, key="meridian/1/meeting_audio/aud.opus"):
    fr = FileRecord(user_id=owner.id, object_key=key, original_name="aud.opus",
                    purpose="meeting_audio", status="active", meeting_id=meeting.id)
    db.add(fr)
    await db.flush()
    return fr


async def add_job(db, meeting):
    j = Job(type="document_process", payload={"meeting_id": meeting.id}, status="pending")
    db.add(j)
    await db.flush()
    return j


async def add_participant(db, meeting, user, role="participant"):
    from app.models.directory import MeetingParticipant
    p = MeetingParticipant(meeting_id=meeting.id, user_id=user.id, role=role)
    db.add(p)
    await db.flush()
    return p


async def add_context_source(db, meeting, source_type="manual"):
    from app.models.context_source import MeetingContextSource
    c = MeetingContextSource(meeting_id=meeting.id, source_type=source_type, included=True, priority=100)
    db.add(c)
    await db.flush()
    return c
