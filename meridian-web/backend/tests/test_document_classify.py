"""Автоклассификация документов: правила, реквизиты, LLM-запасной путь, наследование документов
заказчика/объекта встречей и устойчивость обработки документа к сбою классификатора."""

import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.directory import Customer, ProjectObject
from app.models.document import DocumentChunk, DocumentRecord
from app.models.meeting import MeetingDocumentRecord, MeetingSession
from app.models.user import User
from app.services import document_classify as dc
from app.services import document_processing as dp
from app.services import s3 as s3mod
from app.services.document_context import (
    effective_meeting_document_ids,
    get_relevant_chunks_for_meeting,
)
from app.services.meeting_documents import (
    attach_document,
    detach_document,
    list_meeting_document_items,
    set_document_inclusion,
)


# ---------- правила: тип ----------

@pytest.mark.parametrize("filename,text,expected", [
    ("письмо.pdf", "Исх. № 15 от 01.02.2026\nГенеральному директору", "letter"),
    ("kp.pdf", "Коммерческое предложение на устройство кровли", "offer"),
    ("d.docx", "ДОГОВОР ПОДРЯДА № 12/26\nг. Алматы", "contract"),
    ("x.docx", "Дополнительное соглашение № 2 к Договору подряда № 12/26", "supplement"),
    ("vor.xlsx", "Ведомость объёмов работ по разделу АР", "bor"),
    ("s.xlsx", "Локальная смета № 3 на кладку", "estimate"),
    ("spec.pdf", "Спецификация материалов к объекту", "specification"),
    ("a.pdf", "Акт приёмки выполненных работ", "act"),
    ("p.docx", "Протокол совещания от 12.03.2026", "protocol"),
])
def test_rules_each_type(filename, text, expected):
    result = dc.classify_by_rules(filename, text, None)
    assert result is not None
    assert result.doc_type == expected
    assert result.source == "rules"


def test_rules_type_from_filename_and_sheet_names():
    assert dc.classify_by_rules("Договор подряда №5.pdf", "", None).doc_type == "contract"
    assert dc.classify_by_rules("book.xlsx", "цифры", ["Ведомость объемов"]).doc_type == "bor"


def test_rules_supplement_beats_contract():
    text = "Дополнительное соглашение к Договору подряда № 7 от 01.01.2026"
    assert dc.classify_by_rules("dop.pdf", text, None).doc_type == "supplement"


def test_rules_ambiguous_or_unknown_returns_none():
    # и договор, и протокол в шапке → не уверены
    assert dc.classify_by_rules("a.pdf", "Договор подряда № 1. Протокол разногласий", None) is None
    assert dc.classify_by_rules("a.pdf", "просто текст без признаков", None) is None


def test_rules_type_looks_only_at_document_head():
    far = "x " * 3000 + "Протокол"
    assert dc.classify_by_rules("a.pdf", far, None) is None


# ---------- теги и реквизиты ----------

def test_tags():
    text = "Неустойка 0,1% за день. Аванс 30%. Гарантийный срок 5 лет. Стоимость 1 000 руб. Претензия. Объёмы."
    assert set(dc.extract_tags(text)) == {"penalty", "payment", "warranty", "deadline", "price", "claim", "scope"}
    assert dc.extract_tags("Выполнить дополнительные работы") == ["extra_work"]
    assert dc.extract_tags("ничего особенного") == []


def test_meta_inn_number_date_amount():
    text = (
        "Договор № 12-А/26 от 05.03.2026\n"
        "Заказчик ИНН 7701234567, исполнитель БИН: 123456789012, повтор ИНН 7701234567.\n"
        "Цена договора 1 250 000,50 руб., аванс 300 000 руб."
    )
    meta = dc.extract_meta(text)
    assert meta["inn"] == ["7701234567", "123456789012"]
    assert meta["number"] == "12-А/26"
    assert meta["date"] == "2026-03-05"
    assert meta["amount"] == "1250000.50 RUB"
    # полный текст в мету не попадает
    assert "Цена договора" not in json.dumps(meta, ensure_ascii=False)


def test_meta_inn_limit_and_bad_date():
    text = " ".join(f"ИНН {7700000000 + i}" for i in range(9)) + " 31.02.2026"
    meta = dc.extract_meta(text)
    assert len(meta["inn"]) == 5
    assert "date" not in meta


def test_vocab_is_consistent():
    v = dc.vocab()
    assert {i["key"] for i in v["doc_types"]} == set(dc.DOC_TYPES) and "other" in dc.DOC_TYPES
    assert {i["key"] for i in v["doc_tags"]} == set(dc.DOC_TAGS)
    assert all(i["label"] for i in v["doc_types"] + v["doc_tags"])


# ---------- classify_document: LLM ----------

class _FakeLLM:
    answer: str | Exception | None = None
    calls = 0

    def __init__(self, **kwargs):
        pass

    def set_system_prompt(self, prompt):
        pass

    async def get_suggestion_async(self, prompt, max_tokens=None):
        type(self).calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def llm(monkeypatch):
    async def _keys():
        return {"openrouter": "test-key"}

    _FakeLLM.answer, _FakeLLM.calls = None, 0
    monkeypatch.setattr(dc, "load_api_keys", _keys)
    monkeypatch.setattr(dc, "LLMClient", _FakeLLM)
    return _FakeLLM


async def test_classify_confident_rules_skip_llm(llm):
    llm.answer = json.dumps({"doc_type": "act"})
    res = await dc.classify_document("Коммерческое предложение", "kp.pdf", None)
    assert res.doc_type == "offer" and res.source == "rules"
    assert llm.calls == 0


async def test_classify_without_llm_key_falls_back_to_rules():
    # autouse-фикстура conftest: ключа нет
    res = await dc.classify_document("Неустойка по договору. Срок 10 дней.", "z.pdf", None)
    assert res.doc_type == "other" and res.source == "rules"
    assert set(res.tags) == {"penalty", "deadline"}


async def test_classify_llm_result_merged_with_rules_tags(llm):
    llm.answer = "```json\n" + json.dumps({
        "doc_type": "claim_letter_unknown", "tags": ["claim", "bogus"],
        "counterparty_name": "ООО Ромашка", "number": "77", "date": "10.04.2026",
    }) + "\n```"
    res = await dc.classify_document("Просим выплатить неустойку ИНН 7701234567", "z.pdf", None)
    assert res.doc_type == "other"  # тип вне списка
    assert res.source == "llm"
    assert res.tags == ["penalty", "claim"]  # неизвестный тег отброшен, теги объединены
    assert res.meta["counterparty_name"] == "ООО Ромашка"
    assert res.meta["date"] == "2026-04-10" and res.meta["number"] == "77"
    assert res.meta["inn"] == ["7701234567"]


async def test_classify_llm_valid_type(llm):
    llm.answer = json.dumps({"doc_type": "protocol", "tags": []})
    res = await dc.classify_document("Совещание по объекту", "z.pdf", None)
    assert (res.doc_type, res.source) == ("protocol", "llm")


@pytest.mark.parametrize("answer", [None, "это не JSON", RuntimeError("boom"), TimeoutError()])
async def test_classify_llm_failure_falls_back(llm, answer):
    llm.answer = answer
    res = await dc.classify_document("Срок исполнения 5 дней", "z.pdf", None)
    assert res.doc_type == "other" and res.source == "rules"
    assert res.tags == ["deadline"]
    assert llm.calls == 1


# ---------- обработка документа: классификатор не роняет job ----------

@pytest_asyncio.fixture
async def sqlite_sm(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dp, "async_session", sm)
    try:
        yield sm
    finally:
        await engine.dispose()


async def _mk_user(db, email="u@t.local"):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    return u


def _mock_s3(monkeypatch, text: str):
    async def _dl(key, dest):
        with open(dest, "wb") as f:
            f.write(text.encode("utf-8"))

    async def _put(key, data, content_type="text/plain"):
        return None

    monkeypatch.setattr(s3mod, "download_to", _dl)
    monkeypatch.setattr(s3mod, "put_bytes", _put)


async def test_process_writes_classification_and_matches_customer_by_inn(sqlite_sm, monkeypatch):
    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db)
        db.add(Customer(name="ООО Заказчик", inn="7701234567"))
        db.add(Customer(name="Другой", inn="5000000000"))
        doc = DocumentRecord(owner_user_id=owner.id, created_by_user_id=owner.id, original_name="d.txt",
                             file_ext=".txt", status="uploaded", s3_key="k/d.txt")
        db.add(doc)
        await db.commit()
        doc_id = doc.id
    _mock_s3(monkeypatch, "ДОГОВОР ПОДРЯДА № 5 от 01.02.2026. Заказчик ИНН 7701234567. Неустойка 0,1%. " * 5)

    await dp.handle_document_process({"document_id": doc_id})

    async with sm() as db:
        doc = await db.get(DocumentRecord, doc_id)
        assert doc.status == "ready"
        assert doc.doc_type == "contract" and doc.classify_source == "rules" and doc.classified_at
        assert "penalty" in doc.doc_tags
        assert doc.doc_meta["inn"] == ["7701234567"] and doc.doc_meta["number"] == "5"
        customer = (await db.execute(select(Customer).where(Customer.inn == "7701234567"))).scalar_one()
        assert doc.customer_id == customer.id


async def test_process_keeps_existing_customer(sqlite_sm, monkeypatch):
    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db)
        mine = Customer(name="Мой", inn="1111111111")
        other = Customer(name="По ИНН", inn="7701234567")
        db.add_all([mine, other])
        await db.flush()
        doc = DocumentRecord(owner_user_id=owner.id, created_by_user_id=owner.id, original_name="d.txt",
                             file_ext=".txt", status="uploaded", s3_key="k/d.txt", customer_id=mine.id)
        db.add(doc)
        await db.commit()
        doc_id, mine_id = doc.id, mine.id
    _mock_s3(monkeypatch, "Договор подряда № 5, ИНН 7701234567. " * 10)
    await dp.handle_document_process({"document_id": doc_id})
    async with sm() as db:
        assert (await db.get(DocumentRecord, doc_id)).customer_id == mine_id


async def test_process_survives_classifier_failure(sqlite_sm, monkeypatch, caplog):
    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db)
        doc = DocumentRecord(owner_user_id=owner.id, created_by_user_id=owner.id, original_name="d.txt",
                             file_ext=".txt", status="uploaded", s3_key="k/d.txt")
        db.add(doc)
        await db.commit()
        doc_id = doc.id
    secret = "СЕКРЕТНЫЙ_ТЕКСТ_ДОКУМЕНТА"
    _mock_s3(monkeypatch, f"{secret} цена договора. " * 20)

    async def _boom(*a, **kw):
        raise RuntimeError(secret)

    monkeypatch.setattr(dp, "classify_document", _boom)
    with caplog.at_level("WARNING", logger="meridian.documents"):
        await dp.handle_document_process({"document_id": doc_id})

    async with sm() as db:
        doc = await db.get(DocumentRecord, doc_id)
        assert doc.status == "ready" and doc.processing_error is None
        assert doc.doc_type is None and doc.classified_at is None
        assert (await db.execute(select(DocumentChunk))).scalars().first() is not None
    assert "классификация не удалась" in caplog.text and secret not in caplog.text


# ---------- наследование документов заказчика/объекта ----------

async def _setup(db):
    user = await _mk_user(db, "own@t.local")
    cust_a = Customer(name="A")
    cust_b = Customer(name="B")
    db.add_all([cust_a, cust_b])
    await db.flush()
    obj = ProjectObject(customer_id=cust_a.id, name="Объект 1")
    db.add(obj)
    await db.flush()
    return user, cust_a, cust_b, obj


async def _doc(db, owner, name, *, customer_id=None, object_id=None, status="ready", text=None):
    d = DocumentRecord(owner_user_id=owner.id, created_by_user_id=owner.id, original_name=name,
                       file_ext=".txt", status=status, s3_key=f"k/{name}",
                       customer_id=customer_id, object_id=object_id)
    db.add(d)
    await db.flush()
    if text:
        db.add(DocumentChunk(document_id=d.id, chunk_index=0, text=text))
        await db.flush()
    return d


async def _meeting(db, owner, *, customer_id=None, object_id=None):
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=True, status="active",
                       customer_id=customer_id, object_id=object_id)
    db.add(m)
    await db.flush()
    return m


async def test_inherited_documents_included_by_default(db):
    user, cust_a, cust_b, obj = await _setup(db)
    d_cust = await _doc(db, user, "cust.txt", customer_id=cust_a.id)
    d_obj = await _doc(db, user, "obj.txt", object_id=obj.id)
    d_other = await _doc(db, user, "other.txt", customer_id=cust_b.id)
    d_pending = await _doc(db, user, "pending.txt", customer_id=cust_a.id, status="processing")
    d_free = await _doc(db, user, "free.txt")
    meeting = await _meeting(db, user, customer_id=cust_a.id, object_id=obj.id)

    ids = await effective_meeting_document_ids(db, meeting)
    assert ids == {d_cust.id, d_obj.id}
    assert not ({d_other.id, d_pending.id, d_free.id} & ids)

    items = {i.document_id: i for i in await list_meeting_document_items(db, meeting)}
    assert items[d_cust.id].source == "customer" and items[d_cust.id].included
    assert items[d_obj.id].source == "object"
    assert d_other.id not in items and d_pending.id not in items


async def test_meeting_without_customer_and_object_inherits_nothing(db):
    user, cust_a, _, _ = await _setup(db)
    await _doc(db, user, "cust.txt", customer_id=cust_a.id)
    await _doc(db, user, "free.txt")
    meeting = await _meeting(db, user)
    assert await effective_meeting_document_ids(db, meeting) == set()


async def test_excluded_after_patch_and_reincluded(db):
    user, cust_a, _, _ = await _setup(db)
    d = await _doc(db, user, "cust.txt", customer_id=cust_a.id, text="неустойка за просрочку")
    meeting = await _meeting(db, user, customer_id=cust_a.id)
    assert [c["document_id"] for c in await get_relevant_chunks_for_meeting(db, meeting.id, "неустойка")] == [d.id]

    md, _doc_ = await set_document_inclusion(db, meeting, d.id, included=False, priority=None)
    assert md.included is False and md.added_by_user_id is None
    assert await effective_meeting_document_ids(db, meeting) == set()
    assert await get_relevant_chunks_for_meeting(db, meeting.id, "неустойка") == []
    item = (await list_meeting_document_items(db, meeting))[0]
    assert item.source == "customer" and item.included is False and item.id == md.id

    await set_document_inclusion(db, meeting, d.id, included=True, priority=150)
    assert await effective_meeting_document_ids(db, meeting) == {d.id}
    rows = (await db.execute(select(MeetingDocumentRecord))).scalars().all()
    assert len(rows) == 1 and rows[0].priority == 150  # строка одна, повторный PATCH её обновляет


async def test_patch_of_foreign_document_is_not_found(db):
    user, cust_a, cust_b, _ = await _setup(db)
    d_other = await _doc(db, user, "other.txt", customer_id=cust_b.id)
    meeting = await _meeting(db, user, customer_id=cust_a.id)
    assert await set_document_inclusion(db, meeting, d_other.id, included=False, priority=None) is None
    assert await set_document_inclusion(db, meeting, 99999, included=False, priority=None) is None
    assert await detach_document(db, meeting, d_other.id) is False


async def test_detach_inherited_hides_and_detach_foreign_row_deletes(db):
    user, cust_a, cust_b, _ = await _setup(db)
    d_inh = await _doc(db, user, "inh.txt", customer_id=cust_a.id)
    d_free = await _doc(db, user, "free.txt")
    meeting = await _meeting(db, user, customer_id=cust_a.id)

    assert await detach_document(db, meeting, d_inh.id) is True
    assert await effective_meeting_document_ids(db, meeting) == set()
    # явно прикреплённый чужой документ открепляется совсем
    await attach_document(db, meeting, d_free, user.id)
    assert await effective_meeting_document_ids(db, meeting) == {d_free.id}
    assert await detach_document(db, meeting, d_free.id) is True
    assert await effective_meeting_document_ids(db, meeting) == set()
    assert (await db.execute(select(MeetingDocumentRecord).where(
        MeetingDocumentRecord.document_id == d_free.id))).scalar_one_or_none() is None


async def test_explicitly_attached_inheritable_doc_keeps_meeting_source_and_hides_on_detach(db):
    user, cust_a, _, _ = await _setup(db)
    d = await _doc(db, user, "cust.txt", customer_id=cust_a.id)
    meeting = await _meeting(db, user, customer_id=cust_a.id)
    md = await attach_document(db, meeting, d, user.id)
    again = await attach_document(db, meeting, d, user.id)  # идемпотентно
    assert again.id == md.id
    assert (await list_meeting_document_items(db, meeting))[0].source == "meeting"
    # «открепление» документа заказчика не возвращает его в наследование
    await detach_document(db, meeting, d.id)
    assert await effective_meeting_document_ids(db, meeting) == set()


async def test_attach_after_hide_returns_document(db):
    user, cust_a, _, _ = await _setup(db)
    d = await _doc(db, user, "cust.txt", customer_id=cust_a.id)
    meeting = await _meeting(db, user, customer_id=cust_a.id)
    await detach_document(db, meeting, d.id)
    await attach_document(db, meeting, d, user.id)
    assert await effective_meeting_document_ids(db, meeting) == {d.id}
