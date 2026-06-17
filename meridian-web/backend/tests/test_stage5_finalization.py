"""Тесты финализации встречи (Этап 5).

Эндпоинты (flush-only) — на rollback-сессии. Job — на изолированном SQLite + fake LLM.
"""

import json

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.user import User
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.directory import MeetingParticipant
from app.models.document import DocumentRecord, DocumentChunk
from app.models.job import Job
from app.models.protocol import MeetingDecision, MeetingActionItem, MeetingRisk, MeetingOpenQuestion
from app.services import meeting_finalize as mf
from app.api.history import (
    finalize_meeting_endpoint, get_finalization_status, get_meeting_protocol,
    patch_meeting_protocol, retry_finalization, list_meetings,
)
from app.schemas.finalization import ProtocolPatch
from app.api.mobile import mobile_meeting_detail


FAKE_RESULT = {
    "title": "Переговоры по ЖК Рассвет",
    "micro_summary": "Обсудили цену и сроки, есть предварительная договорённость.",
    "tags": ["цена", "сроки"],
    "meeting_type": "negotiation",
    "protocol_markdown": "# Протокол\n\nОбсуждение условий.",
    "summary_points": [{"text": "Цена обсуждалась", "evidence": [{"timecode": "00:10", "speaker": "Иван", "quote": "цена пять"}]}],
    "decisions": [{"text": "Согласовать цену", "status": "preliminary", "evidence": [{"timecode": "00:12", "speaker": "Иван", "quote": "договорились"}]}],
    "action_items": [{"task": "Прислать смету", "owner": "Иван", "due": "пятница", "status": "open", "evidence": []}],
    "risks": [{"text": "Срыв сроков", "severity": "high", "evidence": []}],
    "open_questions": [{"text": "Кто подписывает?", "evidence": []}],
    "important_quotes": [{"speaker": "Иван", "timecode": "00:12", "quote": "договорились"}],
    "document_references": [{"document_name": "Смета.xlsx", "reason_used": "цена"}],
}


class FakeLLM:
    def __init__(self, *a, **k):
        pass

    def set_system_prompt(self, s):
        pass

    async def get_suggestion_async(self, prompt, max_tokens=None):
        return json.dumps(FAKE_RESULT, ensure_ascii=False)


def _patch_llm(monkeypatch, llm_cls=FakeLLM):
    async def _keys():
        return {"openrouter": "k"}
    monkeypatch.setattr(mf, "load_api_keys", _keys)
    monkeypatch.setattr(mf, "LLMClient", llm_cls)


# ---------- helpers ----------

async def _mk_user(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u); await db.flush(); await db.refresh(u)
    return u


async def _mk_meeting(db, owner, active=False):
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=active,
                       status="finalized", started_at=__import__("datetime").datetime(2026, 1, 1, 10, 0))
    db.add(m); await db.flush(); await db.refresh(m)
    return m


async def _add_segment(db, meeting, text, idx):
    from datetime import datetime, timedelta
    db.add(TranscriptSegmentRecord(
        session_id=meeting.id, segment_id=f"s{meeting.id}_{idx}", text=text,
        start_time=float(idx), end_time=float(idx) + 1, wall_clock=datetime(2026, 1, 1, 10, 0) + timedelta(seconds=idx),
        speaker_id="spk1", origin="live_committed", word_count=len(text.split()),
    ))
    await db.flush()


@pytest_asyncio.fixture
async def sqlite_sm(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(mf, "async_session", sm)
    try:
        yield sm
    finally:
        await engine.dispose()


# ---------- 1,2: endpoints ----------

async def test_finalize_enqueues_job(db):
    owner = await _mk_user(db, "fin1@test.local")
    meeting = await _mk_meeting(db, owner, active=True)
    resp = await finalize_meeting_endpoint(meeting.id, user=owner, db=db)
    assert resp.status == "queued"
    jobs = (await db.execute(select(Job).where(Job.type == "meeting_finalize"))).scalars().all()
    assert any(j.payload.get("meeting_id") == meeting.id for j in jobs)


async def test_finalization_status_endpoint(db):
    owner = await _mk_user(db, "fin2@test.local")
    meeting = await _mk_meeting(db, owner)
    meeting.finalization_status = "completed"
    meeting.protocol_markdown = "# x"
    await db.flush()
    resp = await get_finalization_status(meeting.id, user=owner, db=db)
    assert resp.status == "completed"
    assert resp.has_protocol is True


# ---------- 3,4: job saves protocol + structured rows ----------

async def test_job_saves_protocol(sqlite_sm, monkeypatch):
    _patch_llm(monkeypatch)
    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db, "job1@test.local")
        meeting = await _mk_meeting(db, owner)
        await _add_segment(db, meeting, "Здравствуйте, обсудим цену.", 0)
        await db.commit()
        mid = meeting.id

    await mf.handle_meeting_finalize({"meeting_id": mid})

    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.finalization_status == "completed"
        assert m.title == FAKE_RESULT["title"]
        assert m.micro_summary == FAKE_RESULT["micro_summary"]
        assert json.loads(m.tags_json) == FAKE_RESULT["tags"]
        assert m.protocol_markdown and m.protocol_json


async def test_job_saves_structured_rows(sqlite_sm, monkeypatch):
    _patch_llm(monkeypatch)
    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db, "job2@test.local")
        meeting = await _mk_meeting(db, owner)
        await _add_segment(db, meeting, "Договорились о цене.", 0)
        await db.commit()
        mid = meeting.id

    await mf.handle_meeting_finalize({"meeting_id": mid})

    async with sm() as db:
        dec = (await db.execute(select(func.count(MeetingDecision.id)).where(MeetingDecision.meeting_id == mid))).scalar()
        act = (await db.execute(select(func.count(MeetingActionItem.id)).where(MeetingActionItem.meeting_id == mid))).scalar()
        rsk = (await db.execute(select(func.count(MeetingRisk.id)).where(MeetingRisk.meeting_id == mid))).scalar()
        oq = (await db.execute(select(func.count(MeetingOpenQuestion.id)).where(MeetingOpenQuestion.meeting_id == mid))).scalar()
        assert (dec, act, rsk, oq) == (1, 1, 1, 1)


# ---------- 5: invalid JSON ----------

async def test_job_invalid_json_error(sqlite_sm, monkeypatch):
    class BadLLM(FakeLLM):
        async def get_suggestion_async(self, prompt, max_tokens=None):
            return "это не JSON, просто текст"
    _patch_llm(monkeypatch, BadLLM)
    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db, "job3@test.local")
        meeting = await _mk_meeting(db, owner)
        await _add_segment(db, meeting, "Реплика.", 0)
        await db.commit()
        mid = meeting.id

    await mf.handle_meeting_finalize({"meeting_id": mid})

    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.finalization_status == "error"
        assert m.finalization_error
        assert m.is_finalized is True  # встреча всё равно завершена


# ---------- 6: too-large transcript truncated ----------

async def test_job_truncates_large_transcript(sqlite_sm, monkeypatch):
    captured = {}

    class CapLLM(FakeLLM):
        async def get_suggestion_async(self, prompt, max_tokens=None):
            captured["prompt"] = prompt
            return json.dumps(FAKE_RESULT, ensure_ascii=False)
    _patch_llm(monkeypatch, CapLLM)
    # лимит транскрипта задаём в тесте (не зависим от env): ~28k символов > 4000 → обрезка
    monkeypatch.setattr(mf.get_settings(), "meeting_finalization_max_transcript_chars", 4000)

    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db, "job4@test.local")
        meeting = await _mk_meeting(db, owner)
        for i in range(60):
            await _add_segment(db, meeting, "Длинная реплика " * 30, i)  # ~ много символов
        await db.commit()
        mid = meeting.id

    await mf.handle_meeting_finalize({"meeting_id": mid})
    # лимит транскрипта = 4000 (env в прогоне); должен сработать маркер обрезки
    assert "опущена" in captured.get("prompt", "")


# ---------- 7,8: access ----------

async def test_protocol_open_to_everyone(db):
    # Общая хронология: протокол встречи виден любому авторизованному.
    owner = await _mk_user(db, "acc-owner@test.local")
    stranger = await _mk_user(db, "acc-stranger@test.local")
    meeting = await _mk_meeting(db, owner)
    res = await get_meeting_protocol(meeting.id, user=stranger, db=db)
    assert res is not None


async def test_edit_allowed_for_any_user(db):
    # Общая модель: редактировать протокол может любой авторизованный (не только владелец).
    owner = await _mk_user(db, "v-owner@test.local")
    other = await _mk_user(db, "v-viewer@test.local")
    meeting = await _mk_meeting(db, owner)
    res = await patch_meeting_protocol(meeting.id, ProtocolPatch(title="x"), user=other, db=db)
    assert res is not None


# ---------- 9: mobile detail protocol ----------

async def test_mobile_detail_includes_protocol(db):
    owner = await _mk_user(db, "mob-fin@test.local")
    meeting = await _mk_meeting(db, owner)
    meeting.finalization_status = "completed"
    meeting.micro_summary = "Итог"
    meeting.tags_json = json.dumps(["t1"])
    meeting.protocol_markdown = "# p"
    db.add(MeetingActionItem(meeting_id=meeting.id, task="Сделать", status="open"))
    db.add(MeetingRisk(meeting_id=meeting.id, text="Риск", severity="high"))
    await db.flush()
    detail = await mobile_meeting_detail(meeting.id, user=owner, db=db)
    assert detail.finalization_status == "completed"
    assert detail.has_protocol is True
    assert len(detail.action_items) == 1
    assert len(detail.risks) == 1
    assert detail.tags == ["t1"]


# ---------- 10: history list finalization fields ----------

async def test_history_list_finalization_fields(db):
    owner = await _mk_user(db, "hl@test.local")
    meeting = await _mk_meeting(db, owner)  # is_active=False
    meeting.finalization_status = "completed"
    meeting.micro_summary = "Краткий итог"
    meeting.tags_json = json.dumps(["alpha"])
    await db.flush()
    items = await list_meetings(customer_id=None, object_id=None, status=None, q=None, user=owner, db=db)
    me = [i for i in items if i.id == meeting.id]
    assert me and me[0].finalization_status == "completed"
    assert me[0].micro_summary == "Краткий итог"
    assert me[0].tags == ["alpha"]


# ---------- 11: docs without ready chunks ----------

async def test_job_with_docs_no_chunks(sqlite_sm, monkeypatch):
    _patch_llm(monkeypatch)
    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db, "job5@test.local")
        meeting = await _mk_meeting(db, owner)
        await _add_segment(db, meeting, "Обсудим документ.", 0)
        doc = DocumentRecord(owner_user_id=owner.id, created_by_user_id=owner.id,
                             original_name="Смета.xlsx", file_ext=".xlsx", status="ready")
        db.add(doc); await db.flush()
        from app.models.meeting import MeetingDocumentRecord
        db.add(MeetingDocumentRecord(session_id=meeting.id, document_id=doc.id, included=True, priority=100))
        await db.commit()
        mid = meeting.id

    await mf.handle_meeting_finalize({"meeting_id": mid})  # без чанков — не падает
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.finalization_status == "completed"


# ---------- 12: empty transcript -> partial ----------

async def test_job_empty_transcript_partial(sqlite_sm, monkeypatch):
    _patch_llm(monkeypatch)
    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db, "job6@test.local")
        meeting = await _mk_meeting(db, owner)  # без сегментов
        await db.commit()
        mid = meeting.id

    await mf.handle_meeting_finalize({"meeting_id": mid})
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.finalization_status == "partial"
        assert m.finalization_error and "ранскрипт" in m.finalization_error
        assert m.is_finalized is True
