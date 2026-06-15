"""Тесты controlled auto-learning (Этап 7).

Чистые: dedup/normalize, scope-safety, coerce, промпты, формат блока знаний.
DB (flush): existing_keys, get_relevant_knowledge, approve_candidate, enqueue.
Job (sqlite + fake LLM): handle_learning_extract (порог/source_text/дубли/ошибки).
"""

import json
from datetime import datetime, timedelta

import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.user import User
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.directory import Customer, ProjectObject
from app.models.job import Job
from app.models.knowledge import (
    LearningCandidate, GlossaryTerm, TriggerPhrase, NegotiationPlaybook,
    CounterpartyTrait, ForbiddenPhrase,
)
from app.schemas.learning import LearningExtractionResult, _conf
from app.services import learning_extract as le
from app.services.learning_dedup import normalize, candidate_keys, existing_keys
from app.services.learning_extract import _scope_safe, _coerce_payload
from app.services.learning_approve import build_knowledge_item, approve_candidate
from app.services.knowledge_context import format_knowledge_block, get_relevant_knowledge
from app.core.llm.learning_prompt import build_user_prompt, build_repair_prompt
from app.core.llm.suggestion_prompts import (
    build_auto_cards_prompt, build_manual_cards_prompt, build_strengthen_prompt,
)


# ======================= чистые =======================

# 1: normalize
def test_normalize_yo_case_space():
    assert normalize("  Объём  Работ ") == "объем работ"
    assert normalize("ВОР") == "вор"
    assert normalize(None) == ""


# 2: candidate_keys по типам
def test_candidate_keys_per_type():
    assert candidate_keys("term", {"term": "ВОР", "aliases": ["ведомость"]}) == ["вор", "ведомость"]
    assert candidate_keys("trigger_phrase", {"phrase": "Это дорого"}) == ["это дорого"]
    pk = candidate_keys("playbook", {"situation": "Скидка", "recommended_phrase": "При предоплате"})
    assert pk == ["скидка|при предоплате"]
    assert candidate_keys("forbidden_phrase", {"phrase_or_risk": "Гарантирую"}) == ["гарантирую"]


# 3: scope-safety demotion + trait drop
def test_scope_safe_demotion():
    class M:  # noqa: D401
        customer_id = None
        object_id = None
    m = M()
    assert _scope_safe("object", m) == "global"
    assert _scope_safe("customer", m) == "global"
    assert _scope_safe("object", m, trait=True) is None   # особенность некуда привязать
    m.customer_id = 5
    assert _scope_safe("object", m) == "customer"
    assert _scope_safe("customer", m, trait=True) == "customer"
    m.object_id = 7
    assert _scope_safe("object", m) == "object"


# 4: coerce payload
def test_coerce_payload_term_and_trigger():
    class M:
        customer_id = None
        object_id = None
    m = M()
    assert _coerce_payload("term", {"term": "x"}, m) is None  # слишком короткий
    ok = _coerce_payload("term", {"term": "ВОР", "definition": "вед.", "scope": "global"}, m)
    assert ok["term"] == "ВОР" and ok["scope"] == "global"
    tr = _coerce_payload("trigger_phrase", {"phrase": "дорого", "event_type": "WAT", "scope": "object"}, m)
    assert tr["event_type"] == "other"      # неизвестный enum → other
    assert tr["scope"] == "global"          # нет object/customer → global


def test_coerce_trait_requires_scope_target():
    class M:
        customer_id = None
        object_id = None
    assert _coerce_payload("counterparty_trait", {"trait": "торгуется", "scope": "customer"}, M()) is None


# 5: _conf нормализация
def test_conf_normalize():
    assert _conf(80) == 0.8
    assert _conf(1.5) == 1.0
    assert _conf(0.42) == 0.42
    assert _conf("nan-ish") is None


# 6: LearningExtractionResult lenient
def test_extraction_result_parse_lowercases_type():
    r = LearningExtractionResult(**{"candidates": [
        {"candidate_type": "TERM", "title": "t", "confidence": 200, "payload": {"term": "ВОР"}},
    ]})
    assert r.candidates[0].candidate_type == "term"
    assert r.candidates[0].confidence == 1.0  # 200 → /100 → 2.0 → clamp 1.0


# 7: промпт извлечения
def test_build_user_prompt_contains_sections():
    p = build_user_prompt("Заказчик: ООО", "", "Иван: дорого", "Термины: вор", 15)
    assert "УЖЕ УТВЕРЖДЁННЫЕ ЗНАНИЯ" in p and "вор" in p
    assert "до 15 кандидатов" in p
    assert "candidate_type" in p  # схема включена
    assert "JSON" in build_repair_prompt("мусор")


# 8: формат блока знаний
def test_format_knowledge_block():
    items = {
        "terms": [GlossaryTerm(term="ВОР", definition="ведомость", aliases_json=json.dumps(["вед."]))],
        "triggers": [TriggerPhrase(phrase="дорого", event_type="price_pressure", recommended_reaction="уточнить")],
        "playbooks": [],
        "traits": [CounterpartyTrait(trait="торгуется", recommended_strategy="якорь")],
        "forbidden": [ForbiddenPhrase(phrase_or_risk="гарантирую", better_alternative="планируем")],
    }
    block = format_knowledge_block(items)
    assert "Термины:" in block and "ВОР" in block and "вед." in block
    assert "Триггерные фразы" in block and "дорого" in block
    assert "Особенности контрагента" in block
    assert "НЕ говорить: гарантирую" in block
    assert format_knowledge_block({"terms": [], "triggers": [], "playbooks": [], "traits": [], "forbidden": []}) == ""


# 9: knowledge_context в live-промптах
def test_knowledge_block_in_prompts():
    kb = "Термины:\n- ВОР: ведомость"
    assert "УТВЕРЖДЁННАЯ БАЗА ЗНАНИЙ" in build_auto_cards_prompt("Роль", "цена", "x", "", 2, knowledge_context=kb)
    assert "ВОР" in build_manual_cards_prompt("Роль", "ctx", "x", "", 5, knowledge_context=kb)
    assert "ВОР" in build_strengthen_prompt("Роль", "ctx", "x", "", knowledge_context=kb)
    # без знаний — блока нет
    assert "УТВЕРЖДЁННАЯ БАЗА ЗНАНИЙ" not in build_auto_cards_prompt("Роль", "цена", "x", "", 2)


# 10: build_knowledge_item scope resolution
def test_build_knowledge_item_scope():
    glob = LearningCandidate(owner_user_id=1, customer_id=5, object_id=7, meeting_id=3,
                             candidate_type="term", title="t",
                             payload_json=json.dumps({"term": "ВОР", "definition": "в", "scope": "global"}))
    item = build_knowledge_item(glob)
    assert isinstance(item, GlossaryTerm) and item.customer_id is None and item.object_id is None

    objc = LearningCandidate(owner_user_id=1, customer_id=5, object_id=7, meeting_id=3,
                             candidate_type="playbook", title="t",
                             payload_json=json.dumps({"situation": "s", "recommended_phrase": "p", "scope": "object"}))
    item2 = build_knowledge_item(objc)
    assert isinstance(item2, NegotiationPlaybook) and item2.customer_id == 5 and item2.object_id == 7


# ======================= DB (flush) =======================

async def _mk_user(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u); await db.flush(); await db.refresh(u)
    return u


# 11: existing_keys
async def test_existing_keys(db):
    owner = await _mk_user(db, "lk1@test.local")
    db.add(GlossaryTerm(owner_user_id=owner.id, term="ВОР", definition="в", status="approved",
                        aliases_json=json.dumps(["ведомость"])))
    db.add(GlossaryTerm(owner_user_id=owner.id, term="Архив", definition="a", status="archived"))
    db.add(LearningCandidate(owner_user_id=owner.id, candidate_type="term", title="t",
                             payload_json=json.dumps({"term": "Смета"}), status="pending"))
    await db.flush()
    keys = await existing_keys(db, owner.id, "term")
    assert "вор" in keys and "ведомость" in keys and "смета" in keys
    assert "архив" not in keys  # archived не учитывается


# 12: get_relevant_knowledge — только approved + иерархия scope
async def test_get_relevant_knowledge_scope(db):
    owner = await _mk_user(db, "lk2@test.local")
    cust = Customer(owner_user_id=owner.id, name="C"); db.add(cust); await db.flush()
    other = Customer(owner_user_id=owner.id, name="C2"); db.add(other); await db.flush()
    db.add(GlossaryTerm(owner_user_id=owner.id, term="G", definition="g", scope="global", status="approved"))
    db.add(GlossaryTerm(owner_user_id=owner.id, term="C-term", definition="c", scope="customer",
                        customer_id=cust.id, status="approved"))
    db.add(GlossaryTerm(owner_user_id=owner.id, term="Other", definition="o", scope="customer",
                        customer_id=other.id, status="approved"))
    db.add(GlossaryTerm(owner_user_id=owner.id, term="Arch", definition="x", scope="global", status="archived"))
    await db.flush()
    items = await get_relevant_knowledge(db, owner.id, cust.id, None)
    terms = {t.term for t in items["terms"]}
    assert terms == {"G", "C-term"}  # без Other и без archived


# 13: approve_candidate создаёт элемент + помечает approved
async def test_approve_candidate_creates_item(db):
    owner = await _mk_user(db, "ap1@test.local")
    cand = LearningCandidate(owner_user_id=owner.id, candidate_type="trigger_phrase", title="давление",
                             payload_json=json.dumps({"phrase": "дорого", "event_type": "price_pressure",
                                                      "recommended_reaction": "уточнить", "scope": "global"}),
                             source_text="это дорого", status="pending")
    db.add(cand); await db.flush()
    item = await approve_candidate(db, cand, owner.id)
    await db.flush()
    assert isinstance(item, TriggerPhrase) and item.status == "approved"
    assert item.created_from_candidate_id == cand.id
    assert cand.status == "approved" and cand.reviewed_by_user_id == owner.id
    cnt = (await db.execute(select(func.count(TriggerPhrase.id)).where(TriggerPhrase.owner_user_id == owner.id))).scalar()
    assert cnt == 1


# 14: request_learning_extraction ставит queued + job
async def test_request_extraction_enqueues(db):
    owner = await _mk_user(db, "rq1@test.local")
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=False,
                       started_at=datetime(2026, 1, 1, 10, 0))
    db.add(m); await db.flush()
    ok = await le.request_learning_extraction(db, m.id)
    assert ok is True and m.learning_status == "queued"
    jobs = (await db.execute(select(Job).where(Job.type == "learning_extract"))).scalars().all()
    assert any(j.payload.get("meeting_id") == m.id for j in jobs)


# ======================= Job (sqlite + fake LLM) =======================

FAKE = {"candidates": [
    {"candidate_type": "term", "title": "ВОР", "confidence": 0.8, "source_text": "смотрим ВОР",
     "payload": {"term": "ВОР", "definition": "ведомость объёмов работ", "aliases": ["ведомость"], "scope": "global"}},
    {"candidate_type": "trigger_phrase", "title": "цена", "confidence": 0.7, "source_text": "это дорого",
     "payload": {"phrase": "это дорого", "event_type": "price_pressure", "recommended_reaction": "уточнить", "scope": "global"}},
    {"candidate_type": "counterparty_trait", "title": "торг", "confidence": 0.9, "source_text": "всегда просит скидку",
     "payload": {"trait": "любит торговаться", "recommended_strategy": "держать якорь", "scope": "customer"}},
    {"candidate_type": "forbidden_phrase", "title": "обещание", "confidence": 0.6, "source_text": "гарантирую",
     "payload": {"phrase_or_risk": "гарантирую сроки", "better_alternative": "планируемый срок", "scope": "global"}},
    {"candidate_type": "playbook", "title": "low", "confidence": 0.4, "source_text": "скидка за предоплату",
     "payload": {"situation": "скидка", "recommended_phrase": "при предоплате", "scope": "global"}},
    {"candidate_type": "term", "title": "no-src", "confidence": 0.9, "source_text": "",
     "payload": {"term": "Леса", "definition": "строительные", "scope": "global"}},
]}


class FakeLLM:
    def __init__(self, *a, **k): pass
    def set_system_prompt(self, s): pass
    async def get_suggestion_async(self, prompt, max_tokens=None):
        return json.dumps(FAKE, ensure_ascii=False)


def _patch(monkeypatch, llm=FakeLLM):
    async def _keys(): return {"openrouter": "k"}
    monkeypatch.setattr(le, "load_api_keys", _keys)
    monkeypatch.setattr(le, "LLMClient", llm)


@pytest_asyncio.fixture
async def le_sqlite(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(le, "async_session", sm)
    try:
        yield sm
    finally:
        await engine.dispose()


async def _seed_meeting(sm, with_customer=True, transcript=True):
    async with sm() as db:
        owner = await _mk_user(db, "job@test.local")
        cust = None
        if with_customer:
            cust = Customer(owner_user_id=owner.id, name="ООО Ромашка"); db.add(cust); await db.flush()
        m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=False,
                           customer_id=cust.id if cust else None, started_at=datetime(2026, 1, 1, 10, 0))
        db.add(m); await db.flush()
        if transcript:
            db.add(TranscriptSegmentRecord(
                session_id=m.id, segment_id=f"s{m.id}_0", text="Это дорого, смотрим ВОР.",
                start_time=0.0, end_time=1.0, wall_clock=datetime(2026, 1, 1, 10, 0),
                speaker_id="spk1", origin="live_committed", word_count=4))
        await db.commit()
        return owner.id, m.id


# 15: извлечение — порог/source_text/scope + сохранение pending
async def test_extract_saves_filtered_candidates(le_sqlite, monkeypatch):
    _patch(monkeypatch)
    sm = le_sqlite
    owner_id, mid = await _seed_meeting(sm)
    await le.handle_learning_extract({"meeting_id": mid})
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.learning_status == "completed"
        cands = (await db.execute(select(LearningCandidate).where(LearningCandidate.meeting_id == mid))).scalars().all()
        types = sorted(c.candidate_type for c in cands)
        # playbook(0.4 < 0.55) и term без source_text — отброшены
        assert types == ["counterparty_trait", "forbidden_phrase", "term", "trigger_phrase"]
        assert all(c.status == "pending" for c in cands)
        trait = next(c for c in cands if c.candidate_type == "counterparty_trait")
        assert trait.customer_id is not None  # scope customer → привязан к заказчику встречи


# 16: дубль против approved — отбрасывается
async def test_extract_dedup_against_approved(le_sqlite, monkeypatch):
    _patch(monkeypatch)
    sm = le_sqlite
    owner_id, mid = await _seed_meeting(sm)
    async with sm() as db:
        db.add(GlossaryTerm(owner_user_id=owner_id, term="ВОР", definition="уже есть", status="approved"))
        await db.commit()
    await le.handle_learning_extract({"meeting_id": mid})
    async with sm() as db:
        terms = (await db.execute(select(LearningCandidate).where(
            LearningCandidate.meeting_id == mid, LearningCandidate.candidate_type == "term"))).scalars().all()
        assert len(terms) == 0  # ВОР уже в базе → дубль не сохранён


# 17: пустой транскрипт без протокола → completed, 0 кандидатов
async def test_extract_empty_completes_zero(le_sqlite, monkeypatch):
    _patch(monkeypatch)
    sm = le_sqlite
    owner_id, mid = await _seed_meeting(sm, transcript=False)
    await le.handle_learning_extract({"meeting_id": mid})
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.learning_status == "completed"
        cnt = (await db.execute(select(func.count(LearningCandidate.id)).where(LearningCandidate.meeting_id == mid))).scalar()
        assert cnt == 0


# 18: невалидный JSON → learning_status error (финализация не страдает)
async def test_extract_invalid_json_error(le_sqlite, monkeypatch):
    class BadLLM(FakeLLM):
        async def get_suggestion_async(self, prompt, max_tokens=None):
            return "совсем не json"
    _patch(monkeypatch, BadLLM)
    sm = le_sqlite
    owner_id, mid = await _seed_meeting(sm)
    await le.handle_learning_extract({"meeting_id": mid})
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.learning_status == "error" and m.learning_error
