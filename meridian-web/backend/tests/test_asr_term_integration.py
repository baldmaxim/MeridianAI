# -*- coding: utf-8 -*-
"""Правка терминов в батче: словарь пользователя, effective_transcription, шаг процессора, API."""

import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.core.batch import processor as proc
from app.core.batch.term_corrector import effective_transcription
from app.core.batch.utils import format_transcription_txt, group_words_by_speaker
from app.database import Base, get_db
from app.models.asr_term import AsrTerm
from app.models.batch_job import BatchJob
from app.models.directory import Customer, ProjectObject
from app.models.knowledge import GlossaryTerm
from app.models.user import User
from app.services.asr_lexicon import load_job_lexicon


def _words(text: str, speaker: str = "Speaker_0", t0: float = 0.0):
    return [
        {"text": w, "start": t0 + i, "end": t0 + i + 0.5, "speaker_id": speaker}
        for i, w in enumerate(text.split())
    ]


TRANSCRIPTION = {
    "text": "Купим машины места, сегодня",
    "words": _words("Купим машины места, сегодня"),
}
ITEMS = [{"w0": 1, "w1": 3, "from": "машины места", "to": "машино-места", "term": "машино-место"}]
CORRECTIONS = json.dumps({"v": 1, "lexicon": "x", "items": ITEMS}, ensure_ascii=False)


async def _user(db, email: str) -> User:
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    return u


def _forms(lexicon) -> set[str]:
    return {f.form for f in lexicon.forms}


# ---------- load_job_lexicon ----------

async def test_lexicon_asr_terms_shared_own_and_foreign(db):
    me = await _user(db, "lex-me@t.local")
    other = await _user(db, "lex-other@t.local")
    db.add_all([
        AsrTerm(term="Общекаст", owner_user_id=None, aliases_json=json.dumps(["общий кост"])),
        AsrTerm(term="Моякаст", owner_user_id=me.id),
        AsrTerm(term="Чужекаст", owner_user_id=other.id),
        AsrTerm(term="   ", owner_user_id=None),
        AsrTerm(term="Битыйалиас", owner_user_id=me.id, aliases_json="{не json"),
    ])
    await db.flush()
    forms = _forms(await load_job_lexicon(db, me.id))
    assert {"Общекаст", "общий кост", "Моякаст", "Битыйалиас"} <= forms
    assert "Чужекаст" not in forms
    assert "" not in forms


async def test_lexicon_glossary_only_own_approved(db):
    me = await _user(db, "lex-gl-me@t.local")
    other = await _user(db, "lex-gl-other@t.local")
    db.add_all([
        GlossaryTerm(owner_user_id=me.id, term="Глосстерм", definition="d", status="approved",
                     aliases_json=json.dumps(["глос терм", 5, "  "])),
        GlossaryTerm(owner_user_id=me.id, term="Архивтерм", definition="d", status="archived"),
        GlossaryTerm(owner_user_id=other.id, term="Чужтерм", definition="d", status="approved"),
        GlossaryTerm(owner_user_id=me.id, term="Нетсписка", definition="d", status="approved",
                     aliases_json=json.dumps({"a": 1})),
    ])
    await db.flush()
    forms = _forms(await load_job_lexicon(db, me.id))
    assert {"Глосстерм", "глос терм", "Нетсписка"} <= forms
    assert not ({"Архивтерм", "Чужтерм"} & forms)
    assert "5" not in forms


async def test_lexicon_directory_is_shared_and_base_included(db):
    me = await _user(db, "lex-dir-me@t.local")
    other = await _user(db, "lex-dir-other@t.local")
    cust = Customer(name="ООО «Зеленстрой»", owner_user_id=other.id)
    db.add(cust)
    await db.flush()
    db.add(ProjectObject(name="ЖК Рассвет-Парк", customer_id=cust.id, owner_user_id=other.id))
    await db.flush()
    lexicon = await load_job_lexicon(db, me.id)
    forms = _forms(lexicon)
    assert {"ООО «Зеленстрой»", "ЖК Рассвет-Парк"} <= forms
    assert "машино-место" in lexicon.terms()  # базовый словарь на месте


# ---------- effective_transcription ----------

def _job(**kw):
    return SimpleNamespace(id=1, transcription_json=json.dumps(TRANSCRIPTION, ensure_ascii=False),
                           transcription_corrections_json=kw.get("corr"))


def test_effective_with_corrections_keeps_source_intact():
    job = _job(corr=CORRECTIONS)
    data = effective_transcription(job)
    assert data["text"] == "Купим машино-места, сегодня"
    assert data["words"][1]["orig"] == "машины места,"
    assert json.loads(job.transcription_json) == TRANSCRIPTION


def test_effective_without_corrections_is_source():
    assert effective_transcription(_job()) == TRANSCRIPTION
    assert effective_transcription(_job(corr=json.dumps({"v": 1, "items": []}))) == TRANSCRIPTION


@pytest.mark.parametrize("raw", ["{не json", "[]", '{"items": 5}', "null"])
def test_effective_broken_corrections_fall_back_to_source(raw):
    assert effective_transcription(_job(corr=raw)) == TRANSCRIPTION


def test_effective_none_without_transcription():
    job = SimpleNamespace(id=1, transcription_json=None, transcription_corrections_json=CORRECTIONS)
    assert effective_transcription(job) is None


def test_segments_carry_corrections_without_punctuation():
    segs = group_words_by_speaker(effective_transcription(_job(corr=CORRECTIONS))["words"])
    assert len(segs) == 1
    assert segs[0].text == "Купим машино-места, сегодня"
    assert segs[0].corrections == [{"from": "машины места", "to": "машино-места"}]
    assert group_words_by_speaker(TRANSCRIPTION["words"])[0].corrections == []
    assert "машино-места" in format_transcription_txt(effective_transcription(_job(corr=CORRECTIONS)))


# ---------- шаг правки в процессоре ----------

class _FakeCorrector:
    result: object = None
    error: Exception | None = None
    calls = 0

    def __init__(self, key):
        self.key = key

    async def correct(self, transcription, lexicon):
        _FakeCorrector.calls += 1
        if _FakeCorrector.error:
            raise _FakeCorrector.error
        return _FakeCorrector.result


@pytest.fixture
def step(monkeypatch):
    _FakeCorrector.result = {"v": 1, "lexicon": "x", "items": ITEMS}
    _FakeCorrector.error = None
    _FakeCorrector.calls = 0
    monkeypatch.setattr(proc, "TermCorrector", _FakeCorrector)

    def _run(db, job, enabled=True, key="or-key"):
        monkeypatch.setattr(proc, "get_settings", lambda: SimpleNamespace(batch_term_correction=enabled))
        return proc._correct_terms(db, job, TRANSCRIPTION, key)

    return _run


async def _batch_job(db, email: str, **kw) -> BatchJob:
    user = await _user(db, email)
    job = BatchJob(user_id=user.id, status="transcribing", original_filename="a.ogg",
                   file_path="k", transcription_json=json.dumps(TRANSCRIPTION, ensure_ascii=False), **kw)
    db.add(job)
    await db.flush()
    return job


async def test_step_saves_corrections_and_applies(db, step):
    job = await _batch_job(db, "st1@t.local")
    out = await step(db, job)
    assert out["text"] == "Купим машино-места, сегодня"
    assert json.loads(job.transcription_corrections_json)["items"] == ITEMS
    assert job.status == "transcribing"
    assert TRANSCRIPTION["text"] == "Купим машины места, сегодня"  # вход не изменён


async def test_step_llm_failure_leaves_column_null(db, step):
    _FakeCorrector.result = None
    job = await _batch_job(db, "st2@t.local")
    out = await step(db, job)
    assert out == TRANSCRIPTION
    assert job.transcription_corrections_json is None


async def test_step_exception_does_not_break(db, step):
    _FakeCorrector.error = RuntimeError("boom")
    job = await _batch_job(db, "st3@t.local")
    out = await step(db, job)
    assert out == TRANSCRIPTION
    assert job.transcription_corrections_json is None


async def test_step_disabled_or_no_key_skips(db, step):
    job = await _batch_job(db, "st4@t.local")
    assert await step(db, job, enabled=False) == TRANSCRIPTION
    assert await step(db, job, key=None) == TRANSCRIPTION
    assert _FakeCorrector.calls == 0
    assert job.transcription_corrections_json is None


async def test_step_checkpoint_not_repeated(db, step):
    job = await _batch_job(db, "st5@t.local", transcription_corrections_json=CORRECTIONS)
    out = await step(db, job)
    assert out["text"] == "Купим машино-места, сегодня"
    assert _FakeCorrector.calls == 0


async def test_step_empty_items_checkpoint(db, step):
    _FakeCorrector.result = {"v": 1, "lexicon": "x", "items": []}
    job = await _batch_job(db, "st6@t.local")
    assert await step(db, job) == TRANSCRIPTION
    assert job.transcription_corrections_json is not None


# ---------- API: деталь батча ----------

@pytest_asyncio.fixture
async def api():
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as db:
        user = await _user(db, "api-term@t.local")
        db.add(BatchJob(user_id=user.id, status="done", original_filename="a.ogg", file_path="k",
                        transcription_json=json.dumps(TRANSCRIPTION, ensure_ascii=False),
                        transcription_corrections_json=CORRECTIONS))
        await db.commit()

    async def _db():
        async with sm() as s:
            yield s

    async def _cur():
        return user

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _cur
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_api_detail_returns_corrected_text_and_corrections(api):
    r = await api.get("/api/batch/jobs/1")
    assert r.status_code == 200, r.text
    seg = r.json()["segments"][0]
    assert seg["text"] == "Купим машино-места, сегодня"
    assert seg["corrections"] == [{"from": "машины места", "to": "машино-места"}]


async def test_api_downloads_txt_corrected_json_raw(api):
    txt = await api.get("/api/batch/jobs/1/download/transcript_txt")
    assert "машино-места" in txt.text
    raw = await api.get("/api/batch/jobs/1/download/transcript_json")
    assert json.loads(raw.text) == TRANSCRIPTION
