"""Тесты «предыдущие встречи как контекст» (Этап 8).

Эндпоинты context-sources (flush-only) и сервисы — на rollback-сессии (sqlite).
В live/finalization prompts попадают только компактные итоги, не транскрипты.
"""

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.models.user import User
from app.models.meeting import MeetingSession
from app.models.directory import Customer, ProjectObject, MeetingParticipant
from app.models.protocol import MeetingDecision, MeetingActionItem, MeetingRisk, MeetingOpenQuestion
from app.models.context_source import MeetingContextSource
from app.schemas.context_source import MeetingContextSourceCreate, MeetingContextSourceUpdate
from app.services.previous_meeting_context import get_context_candidates, build_previous_context_block
from app.core.llm.suggestion_prompts import build_auto_cards_prompt
from app.core.llm.finalization_prompt import build_user_prompt
from app.api.context_sources import (
    add_context_source, list_context_sources, update_context_source, delete_context_source,
)
from app.api.mobile import mobile_meeting_detail


# ---------- helpers ----------

async def _mk_user(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u); await db.flush(); await db.refresh(u)
    return u


async def _mk_meeting(db, owner, *, active=False, finalized=True, customer_id=None,
                      object_id=None, day=1, title="Встреча"):
    m = MeetingSession(
        user_id=owner.id, created_by_user_id=owner.id, is_active=active,
        status="finalized" if finalized else "active",
        finalization_status="completed" if finalized else "not_started",
        customer_id=customer_id, object_id=object_id, title=title,
        micro_summary="Кратко по встрече", tags_json='["цена"]',
        protocol_markdown="# протокол" if finalized else None,
        started_at=datetime(2026, 1, day, 10, 0),
    )
    db.add(m); await db.flush(); await db.refresh(m)
    return m


async def _add_protocol(db, meeting):
    db.add(MeetingDecision(meeting_id=meeting.id, text="Согласовать цену", status="preliminary"))
    db.add(MeetingActionItem(meeting_id=meeting.id, task="Прислать смету", owner_text="Иван", due_text="пятница", status="open"))
    db.add(MeetingRisk(meeting_id=meeting.id, text="Срыв сроков", severity="high"))
    db.add(MeetingOpenQuestion(meeting_id=meeting.id, text="Кто подписывает?"))
    await db.flush()


# ---------- 1: создать previous_meeting источник ----------

async def test_add_previous_meeting_source(db):
    owner = await _mk_user(db, "ctx1@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    prev = await _mk_meeting(db, owner, day=2)
    out = await add_context_source(cur.id, MeetingContextSourceCreate(source_id=prev.id), user=owner, db=db)
    assert out.source_type == "previous_meeting" and out.source_id == prev.id and out.included is True
    assert out.summary is not None and out.summary.meeting_id == prev.id


# ---------- 2: нельзя добавить текущую встречу как источник самой себя ----------

async def test_cannot_add_self(db):
    owner = await _mk_user(db, "ctx2@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    with pytest.raises(HTTPException) as e:
        await add_context_source(cur.id, MeetingContextSourceCreate(source_id=cur.id), user=owner, db=db)
    assert e.value.status_code == 422


# ---------- 3: нельзя добавить недоступную прошлую встречу ----------

async def test_cannot_add_inaccessible(db):
    owner = await _mk_user(db, "ctx3-owner@test.local")
    stranger = await _mk_user(db, "ctx3-stranger@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    foreign = await _mk_meeting(db, stranger, day=2)  # чужая встреча
    with pytest.raises(HTTPException) as e:
        await add_context_source(cur.id, MeetingContextSourceCreate(source_id=foreign.id), user=owner, db=db)
    assert e.value.status_code == 403


# ---------- 4: дубль идемпотентен ----------

async def test_duplicate_idempotent(db):
    owner = await _mk_user(db, "ctx4@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    prev = await _mk_meeting(db, owner, day=2)
    a = await add_context_source(cur.id, MeetingContextSourceCreate(source_id=prev.id, priority=100), user=owner, db=db)
    b = await add_context_source(cur.id, MeetingContextSourceCreate(source_id=prev.id, priority=50), user=owner, db=db)
    assert a.id == b.id and b.priority == 50  # та же строка, обновлён приоритет
    srcs = await list_context_sources(cur.id, user=owner, db=db)
    assert len([s for s in srcs if s.source_id == prev.id]) == 1


# ---------- 5: кандидаты — приоритет тот же объект/заказчик ----------

async def test_candidates_priority(db):
    owner = await _mk_user(db, "ctx5@test.local")
    c1 = Customer(owner_user_id=owner.id, name="C1"); db.add(c1)
    c2 = Customer(owner_user_id=owner.id, name="C2"); db.add(c2); await db.flush()
    o1 = ProjectObject(owner_user_id=owner.id, customer_id=c1.id, name="O1"); db.add(o1)
    o2 = ProjectObject(owner_user_id=owner.id, customer_id=c1.id, name="O2"); db.add(o2)
    o3 = ProjectObject(owner_user_id=owner.id, customer_id=c2.id, name="O3"); db.add(o3); await db.flush()

    cur = await _mk_meeting(db, owner, customer_id=c1.id, object_id=o1.id, day=10)
    same_obj = await _mk_meeting(db, owner, customer_id=c1.id, object_id=o1.id, day=2, title="SAME_OBJ")
    same_cust = await _mk_meeting(db, owner, customer_id=c1.id, object_id=o2.id, day=3, title="SAME_CUST")
    other = await _mk_meeting(db, owner, customer_id=c2.id, object_id=o3.id, day=4, title="OTHER")

    cands = await get_context_candidates(db, owner.id, cur.id)
    ids = [c.meeting_id for c in cands]
    assert ids.index(same_obj.id) < ids.index(same_cust.id) < ids.index(other.id)


# ---------- 6: кандидаты исключают текущую встречу ----------

async def test_candidates_exclude_current(db):
    owner = await _mk_user(db, "ctx6@test.local")
    cur = await _mk_meeting(db, owner, day=1)  # finalized+inactive, но это текущая
    other = await _mk_meeting(db, owner, day=2)
    cands = await get_context_candidates(db, owner.id, cur.id)
    ids = [c.meeting_id for c in cands]
    assert cur.id not in ids and other.id in ids


# ---------- 7: кандидаты помечают already_added ----------

async def test_candidates_already_added(db):
    owner = await _mk_user(db, "ctx7@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    prev = await _mk_meeting(db, owner, day=2)
    db.add(MeetingContextSource(meeting_id=cur.id, source_type="previous_meeting", source_id=prev.id))
    await db.flush()
    cands = await get_context_candidates(db, owner.id, cur.id)
    match = [c for c in cands if c.meeting_id == prev.id]
    assert match and match[0].already_added is True


# ---------- 8: provider включает решения/задачи/риски/вопросы ----------

async def test_provider_includes_protocol(db):
    owner = await _mk_user(db, "ctx8@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    prev = await _mk_meeting(db, owner, day=2)
    await _add_protocol(db, prev)
    db.add(MeetingContextSource(meeting_id=cur.id, source_type="previous_meeting", source_id=prev.id, included=True))
    await db.flush()
    block = await build_previous_context_block(db, cur.id, viewer_user_id=owner.id)
    assert "ПРЕДЫДУЩИЕ ВСТРЕЧИ" in block
    assert "Решения:" in block and "Задачи:" in block and "Риски:" in block and "Открытые вопросы:" in block
    assert "Согласовать цену" in block
    # полный транскрипт не передаём — маркеров транскрипта нет
    assert "spk1" not in block


# ---------- 9: provider исключает included=false ----------

async def test_provider_excludes_not_included(db):
    owner = await _mk_user(db, "ctx9@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    prev = await _mk_meeting(db, owner, day=2)
    db.add(MeetingContextSource(meeting_id=cur.id, source_type="previous_meeting", source_id=prev.id, included=False))
    await db.flush()
    block = await build_previous_context_block(db, cur.id, viewer_user_id=owner.id)
    assert block == ""


# ---------- 10: provider уважает лимит символов (per-meeting truncation) ----------

async def test_provider_respects_max_chars(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "previous_meetings_context_per_meeting_max_chars", 120)
    owner = await _mk_user(db, "ctx10@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    prev = await _mk_meeting(db, owner, day=2)
    await _add_protocol(db, prev)
    db.add(MeetingContextSource(meeting_id=cur.id, source_type="previous_meeting", source_id=prev.id))
    await db.flush()
    block = await build_previous_context_block(db, cur.id, viewer_user_id=owner.id)
    assert "[часть сведений опущена]" in block


# ---------- 11: блок попадает в live-промпт ----------

async def test_block_in_live_prompt(db):
    owner = await _mk_user(db, "ctx11@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    prev = await _mk_meeting(db, owner, day=2)
    await _add_protocol(db, prev)
    db.add(MeetingContextSource(meeting_id=cur.id, source_type="previous_meeting", source_id=prev.id))
    await db.flush()
    block = await build_previous_context_block(db, cur.id, viewer_user_id=owner.id)
    prompt = build_auto_cards_prompt("Подрядчик", "цена", "[00:01] ...", "", 2, previous_meetings_context=block)
    assert "ПРЕДЫДУЩИЕ ВСТРЕЧИ, ВЫБРАННЫЕ КАК КОНТЕКСТ" in prompt


# ---------- 12: finalization-промпт трактует прошлые встречи как контекст ----------

def test_finalization_prompt_treats_prev_as_context():
    block = "ПРЕДЫДУЩИЕ ВСТРЕЧИ, ВЫБРАННЫЕ КАК КОНТЕКСТ:\n1. [Meeting #5] Прошлая\n   Решения:\n   - Старое решение"
    p = build_user_prompt("Заказчик: ООО", "Иван: договорились", "", previous_meetings_block=block)
    assert "ПРЕДЫДУЩИЕ ВСТРЕЧИ" in p
    assert "не считай их решения" in p.lower()


# ---------- 13: view-only не может добавлять/удалять ----------

async def test_view_only_cannot_modify(db):
    owner = await _mk_user(db, "ctx13-owner@test.local")
    viewer = await _mk_user(db, "ctx13-viewer@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    prev = await _mk_meeting(db, owner, day=2)
    db.add(MeetingParticipant(meeting_id=cur.id, user_id=viewer.id, role="viewer"))
    src = MeetingContextSource(meeting_id=cur.id, source_type="previous_meeting", source_id=prev.id)
    db.add(src); await db.flush()
    with pytest.raises(HTTPException) as e1:
        await add_context_source(cur.id, MeetingContextSourceCreate(source_id=prev.id), user=viewer, db=db)
    assert e1.value.status_code == 403
    with pytest.raises(HTTPException) as e2:
        await delete_context_source(cur.id, src.id, user=viewer, db=db)
    assert e2.value.status_code == 403


# ---------- 14: participant (edit) может добавлять/удалять ----------

async def test_participant_can_modify(db):
    owner = await _mk_user(db, "ctx14-owner@test.local")
    editor = await _mk_user(db, "ctx14-editor@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    # editor — участник текущей встречи И создатель прошлой (значит имеет к ней доступ)
    db.add(MeetingParticipant(meeting_id=cur.id, user_id=editor.id, role="participant"))
    prev = await _mk_meeting(db, editor, day=2)
    await db.flush()
    out = await add_context_source(cur.id, MeetingContextSourceCreate(source_id=prev.id), user=editor, db=db)
    assert out.source_id == prev.id
    res = await delete_context_source(cur.id, out.id, user=editor, db=db)
    assert res["ok"] is True


# ---------- 15: mobile detail отдаёт выбранный контекст read-only ----------

async def test_mobile_detail_previous_context(db):
    owner = await _mk_user(db, "ctx15@test.local")
    cur = await _mk_meeting(db, owner, active=True, finalized=False)
    prev = await _mk_meeting(db, owner, day=2, title="Прошлая встреча")
    db.add(MeetingContextSource(meeting_id=cur.id, source_type="previous_meeting", source_id=prev.id, included=True))
    await db.flush()
    detail = await mobile_meeting_detail(cur.id, user=owner, db=db)
    assert len(detail.previous_context) == 1
    assert detail.previous_context[0].meeting_id == prev.id
    assert detail.previous_context[0].title == "Прошлая встреча"
