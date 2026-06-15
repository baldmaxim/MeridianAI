"""Тесты структурированных подсказок (Этап 6).

Парсер/safety/промпты — чистые. Событие WS и персист — на SessionManager (без сети).
"""

import json

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.database as appdb
from app.models.meeting import MeetingSuggestion
from app.schemas.suggestion import SuggestionCard, SuggestionResponse, SuggestionEvidence
from app.services.suggestion_parser import (
    parse_suggestion_response, apply_safety_checks, fallback_response, extract_json_from_text,
)
from app.core.llm.suggestion_prompts import build_auto_cards_prompt, build_manual_cards_prompt
from app.services.session_manager import SessionManager


# ---------- 1–3: parsing ----------

def test_parse_valid_response():
    raw = json.dumps({"cards": [{"type": "ask", "title": "t", "text": "Какой срок?", "why": "уточнить", "confidence": 0.7, "evidence": [{"source": "transcript", "text": "x"}]}]})
    r = parse_suggestion_response(raw, "manual")
    assert r is not None and len(r.cards) == 1
    assert r.cards[0].type == "ask" and r.cards[0].source_mode == "manual"


def test_parse_fenced_json():
    raw = "```json\n{\"cards\": [{\"type\": \"risk\", \"text\": \"риск устной договорённости\", \"evidence\": []}]}\n```"
    r = parse_suggestion_response(raw, "auto")
    assert r is not None and r.cards[0].type == "risk"


def test_parse_single_card_object():
    raw = json.dumps({"type": "say_now", "text": "Предлагаю зафиксировать", "evidence": []})
    r = parse_suggestion_response(raw, "auto")
    assert r is not None and len(r.cards) == 1 and r.cards[0].type == "say_now"


# ---------- 4: invalid -> degraded fallback ----------

def test_invalid_json_fallback():
    assert parse_suggestion_response("это не json", "auto") is None
    fb = fallback_response("test reason", raw_text="bad")
    assert fb.degraded is True
    assert len(fb.cards) == 1
    assert fb.cards[0].needs_user_check is True
    assert fb.cards[0].type in ("clarify", "pause")


# ---------- 5: confidence normalize ----------

def test_confidence_normalized():
    c1 = SuggestionCard(type="ask", text="q", confidence=80)
    c2 = SuggestionCard(type="ask", text="q", confidence=1.5)
    c3 = SuggestionCard(type="ask", text="q", confidence=0.42)
    assert c1.confidence == 0.8
    assert c2.confidence == 1.0
    assert c3.confidence == 0.42
    e = SuggestionEvidence(source="transcript", text="x", confidence=90)
    assert e.confidence == 0.9


# ---------- 6: empty evidence + high confidence -> needs_user_check ----------

def test_empty_evidence_high_confidence_flagged():
    card = SuggestionCard(type="counter", text="контр", confidence=0.9, evidence=[])
    [out] = apply_safety_checks([card], "")
    assert out.needs_user_check is True
    assert out.confidence <= 0.55


# ---------- 7: document evidence unknown ref -> needs_user_check ----------

def test_document_evidence_unknown_ref_flagged():
    card = SuggestionCard(
        type="say_now", text="смотрите смету", confidence=0.6,
        evidence=[SuggestionEvidence(source="document", ref="Левый.pdf, стр. 9", text="цена")],
    )
    [out] = apply_safety_checks([card], "Релевантные фрагменты документов:\n[Документ: Смета.xlsx | Лист: ВОР]\n...")
    assert out.needs_user_check is True


# ---------- 8: trade_concession without condition flagged ----------

def test_trade_concession_without_condition_flagged():
    bad = SuggestionCard(type="trade_concession", text="дадим скидку 5%", confidence=0.6,
                         evidence=[SuggestionEvidence(source="transcript", text="скидка")])
    good = SuggestionCard(type="trade_concession", text="скидка 5% если подпишете сегодня", confidence=0.6,
                          evidence=[SuggestionEvidence(source="transcript", text="скидка")])
    [b] = apply_safety_checks([bad], "")
    [g] = apply_safety_checks([good], "")
    assert b.needs_user_check is True
    # good остаётся валидным по условности (но empty-evidence-check к нему не применяется, т.к. evidence есть)
    assert "если" in good.text.lower()


# ---------- 9/13: WS event has cards + backward-compat ----------

async def test_ws_event_cards_and_backward_compat():
    sm = SessionManager(0)
    captured = []

    async def cap(d):
        captured.append(d)
    sm.set_ws_send(cap)

    resp = SuggestionResponse(cards=[SuggestionCard(type="ask", text="Какой срок?", confidence=0.8,
                                                    evidence=[SuggestionEvidence(source="transcript", text="срок")])])
    await sm._send_cards_event(resp, "manual")
    msg = captured[0]
    assert msg["type"] == "suggestion"
    assert "cards" in msg and len(msg["cards"]) == 1
    # backward-compat поля
    assert msg["text"] == "Какой срок?"
    assert msg["suggestion_type"] == "ask"
    assert msg["confidence"] == 80


# ---------- 10/11: prompts ----------

def test_auto_prompt_max_cards():
    p = build_auto_cards_prompt("Подрядчик", "цена", "[00:01] Заказчик: дорого", "", 2)
    assert "0–2" in p
    assert "Не выдумывай" in p


def test_manual_prompt_count():
    p = build_manual_cards_prompt("Подрядчик", "Тема: ЖК", "[00:01] ...", "", 5)
    assert "3–5" in p
    assert "ask/clarify" in p


# ---------- 12: persistence ----------

@pytest_asyncio.fixture
async def sqlite_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(appdb, "async_session", sm)
    try:
        yield sm
    finally:
        await engine.dispose()


async def test_persist_card(sqlite_db):
    sm_sess = SessionManager(1)
    sm_sess.db_session_id = 1
    card = SuggestionCard(type="fixation", title="Зафиксировать", text="Запишем письменно",
                          why="устная договорённость", confidence=0.7,
                          evidence=[SuggestionEvidence(source="transcript", ref="00:10", text="договорились")])
    await sm_sess._persist_card(card, "manual")

    from sqlalchemy import select
    async with sqlite_db() as db:
        row = (await db.execute(select(MeetingSuggestion).where(MeetingSuggestion.session_id == 1))).scalar_one()
        assert row.card_json and "fixation" in row.card_json
        assert row.evidence_json and "transcript" in row.evidence_json
        assert row.why == "устная договорённость"
        assert row.source_mode == "manual"
        assert row.suggestion_type == "fixation"
        assert row.needs_user_check is False
