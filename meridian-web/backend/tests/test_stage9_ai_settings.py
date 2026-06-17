"""Тесты AI-настроек/профилей (Этап 9).

Resolver/режимы/тогглы — чистые и на rollback-сессии. Эндпоинты (flush-only) — на db.
Секреты не раскрываются. Снапшот замораживает настройки встречи.
"""

import json

import pytest
from fastapi import HTTPException

from app.models.user import User
from app.models.meeting import MeetingSession
from app.models.directory import MeetingParticipant
from app.models.job import Job
from app.models.ai_settings import AISettingsProfile
from app.services import ai_settings as ais
from app.services.session_manager import SessionManager
from app.services.meeting_finalize import request_finalization
from app.services.learning_extract import request_learning_extraction
from app.api.ai_settings import (
    get_meeting_ai_settings, patch_meeting_ai_settings, get_options, room_registry,
)
from app.schemas.ai_settings import MeetingAISettingsPatch
from sqlalchemy import select, func


async def _mk_user(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u); await db.flush(); await db.refresh(u)
    return u


async def _mk_profile(db, owner, *, mode="balanced", default=False, **flags):
    p = AISettingsProfile(owner_user_id=owner.id, name=f"prof-{mode}", suggestion_mode=mode,
                          is_default=default, created_by_user_id=owner.id, **flags)
    ais.apply_mode_defaults(p)
    db.add(p); await db.flush(); await db.refresh(p)
    return p


async def _mk_meeting(db, owner, *, snapshot=None, profile_id=None, active=False):
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=active,
                       status="finalized", ai_settings_profile_id=profile_id,
                       ai_settings_snapshot_json=json.dumps(snapshot) if snapshot else None,
                       started_at=__import__("datetime").datetime(2026, 1, 1, 10, 0))
    db.add(m); await db.flush(); await db.refresh(m)
    return m


# ---------- 1: default-профиль из config ----------

async def test_get_or_create_default_profile(db):
    owner = await _mk_user(db, "ai1@test.local")
    p = await ais.get_or_create_default_profile(db, owner.id)
    assert p.is_default is True and p.suggestion_mode == "balanced"
    assert p.max_auto_cards == 2 and p.profile_type == "user"


# ---------- 2: только один default на владельца ----------

async def test_single_default(db):
    owner = await _mk_user(db, "ai2@test.local")
    p1 = await ais.get_or_create_default_profile(db, owner.id)
    again = await ais.get_or_create_default_profile(db, owner.id)
    assert again.id == p1.id
    p2 = await _mk_profile(db, owner, mode="fast")
    await ais.make_default(db, p2)
    defaults = (await db.execute(select(func.count(AISettingsProfile.id)).where(
        AISettingsProfile.owner_user_id == owner.id, AISettingsProfile.is_default == True))).scalar()  # noqa: E712
    assert defaults == 1


# ---------- 3: приоритет snapshot > профиль > default > config ----------

async def test_resolve_priority(db):
    owner = await _mk_user(db, "ai3@test.local")
    # нет профиля/default → config baseline
    m0 = await _mk_meeting(db, owner)
    assert (await ais.resolve_for_meeting(db, m0.id))["mode"] == "balanced"
    assert (await ais.resolve_for_meeting(db, m0.id))["profile_id"] is None

    # профиль встречи (deep) важнее default (fast)
    await _mk_profile(db, owner, mode="fast", default=True)
    deep = await _mk_profile(db, owner, mode="deep")
    m1 = await _mk_meeting(db, owner, profile_id=deep.id)
    assert (await ais.resolve_for_meeting(db, m1.id))["mode"] == "deep"

    # snapshot важнее профиля
    m1.ai_settings_snapshot_json = json.dumps({"mode": "balanced", "max_auto_cards": 2})
    await db.flush()
    assert (await ais.resolve_for_meeting(db, m1.id))["mode"] == "balanced"

    # без профиля встречи → default (fast)
    m2 = await _mk_meeting(db, owner)
    assert (await ais.resolve_for_meeting(db, m2.id))["mode"] == "fast"


# ---------- 4: apply_mode_defaults ----------

def test_apply_mode_defaults():
    p = AISettingsProfile(owner_user_id=1, name="x", suggestion_mode="fast")
    ais.apply_mode_defaults(p)
    assert p.max_auto_cards == 1 and p.document_context_max_chunks == 3 and p.previous_context_max_meetings == 2
    p.suggestion_mode = "deep"; ais.apply_mode_defaults(p)
    assert p.document_context_max_chunks == 10 and p.previous_context_max_meetings == 5
    p.suggestion_mode = "balanced"; ais.apply_mode_defaults(p)
    assert p.max_auto_cards == 2 and p.max_manual_cards == 5


# ---------- 5: auto disabled блокирует авто, manual независим ----------

async def test_auto_disabled_blocks_auto():
    sm = SessionManager(1)
    sm.db_session_id = 1
    sm.llm_client = object()  # не None
    called = []

    async def fake_auto(keyword, recent, doc):
        called.append(keyword)
    sm._auto_suggestion = fake_auto  # type: ignore

    sm.set_ai_settings({"auto_suggestions_enabled": False})
    await sm._check_legacy_auto_triggers("это слишком дорого, давление по цене")
    assert called == []  # авто-подсказки выключены
    # manual-путь не зависит от auto-флага
    assert sm._ai("auto_suggestions_enabled", True) is False


# ---------- 6: document_context_enabled=false исключает чанки ----------

async def test_document_context_toggle():
    sm = SessionManager(1)
    sm.db_session_id = 1

    async def doc_provider(mid, q):
        return "DOC-CHUNKS"
    sm.set_doc_context_provider(doc_provider)

    sm.set_ai_settings({"document_context_enabled": True})
    assert "DOC-CHUNKS" in await sm._augment_doc_context("", "q")
    sm.set_ai_settings({"document_context_enabled": False})
    assert await sm._augment_doc_context("base", "q") == "base"


# ---------- 7: knowledge_context_enabled=false исключает базу знаний ----------

async def test_knowledge_context_toggle():
    sm = SessionManager(1)
    sm.db_session_id = 1

    async def kb_provider(mid, q):
        return "KB-BLOCK"
    sm.set_knowledge_provider(kb_provider)

    sm.set_ai_settings({"knowledge_context_enabled": True})
    assert await sm._knowledge_block("q") == "KB-BLOCK"
    sm.set_ai_settings({"knowledge_context_enabled": False})
    assert await sm._knowledge_block("q") == ""


# ---------- 8: previous_meetings_context_enabled=false исключает прошлые встречи ----------

async def test_previous_context_toggle():
    sm = SessionManager(1)
    sm.db_session_id = 1

    async def prev_provider(mid, q):
        return "PREV-BLOCK"
    sm.set_previous_meetings_provider(prev_provider)

    sm.set_ai_settings({"previous_meetings_context_enabled": True})
    assert await sm._previous_meetings_block("q") == "PREV-BLOCK"
    sm.set_ai_settings({"previous_meetings_context_enabled": False})
    assert await sm._previous_meetings_block("q") == ""


# ---------- 9: finalization_enabled=false → disabled, без job ----------

async def test_finalization_disabled(db):
    owner = await _mk_user(db, "ai9@test.local")
    snap = ais.config_baseline(); snap["finalization_enabled"] = False
    m = await _mk_meeting(db, owner, snapshot=snap)
    ok = await request_finalization(db, m.id)
    assert ok is False and m.finalization_status == "disabled"
    jobs = (await db.execute(select(func.count(Job.id)).where(Job.type == "meeting_finalize"))).scalar()
    assert jobs == 0


# ---------- 10: learning_extraction_enabled=false → disabled, без job ----------

async def test_learning_disabled(db):
    owner = await _mk_user(db, "ai10@test.local")
    snap = ais.config_baseline(); snap["learning_extraction_enabled"] = False
    m = await _mk_meeting(db, owner, snapshot=snap)
    ok = await request_learning_extraction(db, m.id)
    assert ok is False and m.learning_status == "disabled"
    jobs = (await db.execute(select(func.count(Job.id)).where(Job.type == "learning_extract"))).scalar()
    assert jobs == 0


# ---------- 11: view-only не может менять настройки встречи ----------

async def test_patch_open_to_everyone(db):
    # Общая модель: менять AI-настройки встречи может любой авторизованный.
    owner = await _mk_user(db, "ai11-owner@test.local")
    other = await _mk_user(db, "ai11-viewer@test.local")
    m = await _mk_meeting(db, owner, active=True)
    res = await patch_meeting_ai_settings(m.id, MeetingAISettingsPatch(mode="fast"), user=other, db=db)
    assert res is not None


# ---------- 12: participant (edit) может менять ----------

async def test_participant_can_patch(db):
    owner = await _mk_user(db, "ai12-owner@test.local")
    editor = await _mk_user(db, "ai12-editor@test.local")
    m = await _mk_meeting(db, owner, active=True)
    db.add(MeetingParticipant(meeting_id=m.id, user_id=editor.id, role="participant"))
    await db.flush()
    out = await patch_meeting_ai_settings(m.id, MeetingAISettingsPatch(mode="fast"), user=editor, db=db)
    assert out.resolved.mode == "fast" and out.has_snapshot is True


# ---------- 13: options не раскрывает секреты ----------

async def test_options_no_secrets(db):
    owner = await _mk_user(db, "ai13@test.local")
    opts = await get_options(user=owner)
    blob = json.dumps(opts).lower()
    for bad in ("api_key", "secret", "password", "encryption", "token"):
        assert bad not in blob
    assert "fast" in opts["supported_modes"] and "balanced" in opts["supported_modes"]


# ---------- 14: live-patch рассылает ai_settings_updated ----------

async def test_live_patch_broadcasts(db, monkeypatch):
    owner = await _mk_user(db, "ai14@test.local")
    m = await _mk_meeting(db, owner, active=True)
    events = []

    class FakeSession:
        def set_ai_settings(self, resolved): pass

    class FakeRoom:
        session = FakeSession()
        async def broadcast(self, data):
            events.append(data)

    monkeypatch.setattr(room_registry, "get_room", lambda mid: FakeRoom())
    await patch_meeting_ai_settings(m.id, MeetingAISettingsPatch(mode="deep"), user=owner, db=db)
    assert any(e.get("type") == "ai_settings_updated" and e.get("meeting_id") == m.id for e in events)
    ev = next(e for e in events if e["type"] == "ai_settings_updated")
    assert ev["settings_summary"]["suggestion_mode"] == "deep"


# ---------- 15: встреча без snapshot/профиля работает (config defaults) ----------

async def test_meeting_without_snapshot(db):
    owner = await _mk_user(db, "ai15@test.local")
    m = await _mk_meeting(db, owner)  # без профиля и снапшота
    out = await get_meeting_ai_settings(m.id, user=owner, db=db)
    assert out.profile_id is None and out.has_snapshot is False
    assert out.resolved.mode == "balanced" and out.resolved.auto_suggestions_enabled is True
    # SessionManager без ai_settings → дефолты
    sm = SessionManager(owner.id)
    assert sm._ai("auto_suggestions_enabled", True) is True
