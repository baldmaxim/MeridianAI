"""Тесты segment-level коррекций диаризации (Этап 8)."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.models.user import User
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.services import speaker_roles as srsvc
from app.services import speaker_corrections as scsvc
from app.services.speaker_corrections import resolve_speaker_for_segment
from app.services.conversation_tree import ConversationTreeService
from app.api.speaker_corrections import (
    get_speaker_corrections, put_speaker_correction, delete_speaker_correction,
)
from app.schemas.speaker_correction import SpeakerSegmentCorrectionPut


async def _mk_user(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u); await db.flush(); await db.refresh(u)
    return u


async def _mk_meeting(db, owner):
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=True,
                       status="active", started_at=datetime(2026, 1, 1, 10, 0))
    db.add(m); await db.flush(); await db.refresh(m)
    return m


async def _add_segment(db, meeting_id, seg_id, label, text, idx):
    db.add(TranscriptSegmentRecord(
        session_id=meeting_id, segment_id=seg_id, text=text,
        start_time=float(idx), end_time=float(idx) + 1,
        wall_clock=datetime(2026, 1, 1, 10, 0) + timedelta(seconds=idx),
        speaker_id="spk", speaker_label=label, origin="live_committed", word_count=len(text.split())))
    await db.flush()


# ── resolver (pure) ───────────────────────────────────────────────────────────

def _corr(**kw):
    base = {"corrected_speaker_label": None, "side": None}
    base.update(kw)
    return SimpleNamespace(**base)


def test_resolver_priority_segment_side_wins():
    roles = {"DG_S0": "self"}
    corrections = {"k1": _corr(side="opponent")}
    r = resolve_speaker_for_segment("k1", "DG_S0", corrections, roles)
    assert r.side == "opponent"  # коррекция реплики важнее роли спикера
    assert r.corrected is True


def test_resolver_corrected_label_then_original():
    roles = {"DG_S0": "self", "DG_S1": "opponent"}
    # corrected_label → его роль
    r = resolve_speaker_for_segment("k", "DG_S0", {"k": _corr(corrected_speaker_label="DG_S1")}, roles)
    assert r.effective_speaker_label == "DG_S1"
    assert r.side == "opponent"
    # без коррекции → роль оригинального спикера
    r2 = resolve_speaker_for_segment("none", "DG_S0", {}, roles)
    assert r2.side == "self"
    assert r2.corrected is False


def test_resolver_unknown_when_no_role():
    r = resolve_speaker_for_segment("x", "DG_S9", {}, {})
    assert r.side is None
    assert r.effective_speaker_label == "DG_S9"


# ── upsert / empty / delete ───────────────────────────────────────────────────

async def test_upsert_and_empty_not_stored(db):
    owner = await _mk_user(db, "scu@test.local")
    m = await _mk_meeting(db, owner)
    row = await scsvc.upsert_segment_correction(db, m.id, " segA ", side="not_us", user_id=owner.id)
    assert row is not None and row.side == "opponent" and row.segment_key == "segA"

    # пустая коррекция (нет corrected/side/note) удаляет существующую
    cleared = await scsvc.upsert_segment_correction(db, m.id, "segA", side="", corrected_speaker_label="")
    assert cleared is None
    assert await scsvc.list_segment_corrections(db, m.id) == {}


async def test_bulk_upsert(db):
    owner = await _mk_user(db, "scb@test.local")
    m = await _mk_meeting(db, owner)
    items = [
        SimpleNamespace(segment_key="s1", original_speaker_label="DG_S0",
                        corrected_speaker_label=None, side="self", note=None),
        SimpleNamespace(segment_key="s2", original_speaker_label="DG_S0",
                        corrected_speaker_label=None, side="opponent", note=None),
    ]
    out = await scsvc.bulk_upsert_segment_corrections(db, m.id, items, user_id=owner.id)
    assert {o.segment_key: o.side for o in out} == {"s1": "self", "s2": "opponent"}


# ── tree rebuild respects per-segment correction ──────────────────────────────

async def test_tree_rebuild_applies_segment_correction(db):
    owner = await _mk_user(db, "sct@test.local")
    m = await _mk_meeting(db, owner)
    await _add_segment(db, m.id, f"s{m.id}_0", "Иван", "Цена слишком высокая", 0)
    await _add_segment(db, m.id, f"s{m.id}_1", "Иван", "Цена нас полностью устраивает", 1)
    await srsvc.upsert_role(db, m.id, "Иван", side="self")  # обе реплики Ивана = self
    # но вторую реплику относим к другой стороне
    await scsvc.upsert_segment_correction(db, m.id, f"s{m.id}_1", side="opponent")

    tree = await ConversationTreeService().rebuild_from_segments(db, m.id)
    price = next(t for t in tree.topics if t.normalized_key == "price")
    assert price.our_summary  # первая реплика — наша сторона
    assert price.opponent_summary  # вторая — другая сторона (по коррекции)


# ── API ───────────────────────────────────────────────────────────────────────

# ── SessionManager: коррекции в prompt-facing транскрипте ─────────────────────

def test_session_resolve_corrected_label():
    from app.services.session_manager import SessionManager
    sm = SessionManager(user_id=1)
    sm.set_speaker_role("Иван", "opponent")
    sm.set_speaker_segment_corrections({"s9": {"side": None, "corrected_speaker_label": "Иван"}})
    seg = SimpleNamespace(segment_id="s9", speaker_label="DG_S0", speaker_id="DG_S0", speaker="DG_S0")
    label, side = sm._resolve_segment(seg)
    assert label == "Иван"
    assert side == "opponent"  # роль corrected_label


def test_session_segment_side_in_prompt_transcript():
    from app.services.session_manager import SessionManager
    sm = SessionManager(user_id=1)
    sm.set_speaker_role("DG_S0", "self")
    seg = SimpleNamespace(
        segment_id="seg1", speaker_label="DG_S0", speaker_id="DG_S0",
        text="Цена устраивает", wall_clock=datetime.now(), is_low_confidence=False,
    )
    sm._committed_segments = [seg]
    assert "[МЫ]" in sm._get_committed_context()  # роль спикера

    # коррекция стороны реплики → транскрипт для prompt помечает «НЕ МЫ»
    sm.set_speaker_segment_corrections({"seg1": {"side": "opponent", "corrected_speaker_label": None}})
    ctx = sm._get_committed_context()
    assert "[НЕ МЫ]" in ctx
    assert "[МЫ]" not in ctx


async def test_api_put_get_delete(db):
    owner = await _mk_user(db, "sca@test.local")
    m = await _mk_meeting(db, owner)
    rows = await put_speaker_correction(
        m.id, "segZ", SpeakerSegmentCorrectionPut(side="opponent", original_speaker_label="DG_S0"),
        user=owner, db=db,
    )
    assert any(r.segment_key == "segZ" and r.side == "opponent" for r in rows)

    got = await get_speaker_corrections(m.id, user=owner, db=db)
    assert len(got) == 1

    res = await delete_speaker_correction(m.id, "segZ", user=owner, db=db)
    assert res == {"ok": True}
    assert await get_speaker_corrections(m.id, user=owner, db=db) == []
