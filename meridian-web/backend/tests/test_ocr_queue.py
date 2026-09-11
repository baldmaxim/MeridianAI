# -*- coding: utf-8 -*-
"""Очередь распознавания сканов для агента на компьютере пользователя.

Модель chandra-ocr-2 работает в LM Studio за NAT, сервер до неё не достучится. Документ-скан
ставится в очередь, агент сам забирает его по HTTPS, сдаёт текст постранично, и документ
уходит в обычную обработку. Компьютер могут выключить посреди работы — аренда это переживает.
"""

from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.models.document import DocumentChunk, DocumentRecord
from app.models.job import Job
from app.models.ocr import DocumentOcrPage, DocumentOcrTask, OcrAgent
from app.models.user import User
from app.services import document_processing as dp
from app.services import ocr_queue as q
from app.services import s3 as s3mod

BROKEN = (
    "TepMHHOJiorust B HacTo.sn.a:eM ,.qorosope, ecm1 KOHTeKCT He npe,nnonaraeT HHoro "
    "CJIOBa 03Haqa10uu,1e e,nHHCTBeHHOe qlfCJIO BhlDOJIUeuue CTpOHTeJihHO MOHTruKHhIX "
    "pa6oT MaTepHaJIOB CTpOHTeJihCTBa O6opy)].OBaHIDI Heo6XO)].HMhIX BhmOJTHeHHR pa6oT "
    "TepMHHOJiorust KOHTeKCT npe,nnonaraeT BhlDOJIUeuue CTpOHTeJihHO MOHTruKHhIX MaTepHaJIOB"
)
PAGE_1 = ("Пункт 7.3. Подрядчик выполняет строительно-монтажные работы в срок сорок пять "
          "календарных дней с даты передачи фронта работ по акту.")
PAGE_2 = ("Пункт 9.1. За нарушение срока Заказчик вправе начислить неустойку в размере ноль "
          "целых одна десятая процента от стоимости этапа за каждый день просрочки.")

URL = lambda key: f"https://s3.example/{key}?sig=x"  # noqa: E731


@pytest_asyncio.fixture
async def sm(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dp, "async_session", maker)
    try:
        yield maker
    finally:
        await engine.dispose()


async def _doc(db, status="uploaded", ext=".pdf") -> DocumentRecord:
    user = User(email=f"ocr{datetime.utcnow().timestamp()}@test.local", password_hash="x",
                role="admin", is_active=True)
    db.add(user)
    await db.flush()
    doc = DocumentRecord(owner_user_id=user.id, created_by_user_id=user.id,
                         original_name="Договор ГП.pdf", file_ext=ext, status=status,
                         s3_key="meridian/1/documents/scan.pdf")
    db.add(doc)
    await db.flush()
    return doc


async def _agent(db, name="ПК") -> tuple[OcrAgent, str]:
    return await q.enroll_agent(db, name, None)


# ---------- токен агента ----------

async def test_token_is_stored_only_as_hash(sm):
    async with sm() as db:
        agent, token = await _agent(db)
        await db.commit()
        assert token not in agent.token_hash and len(agent.token_hash) == 64
        assert (await q.authenticate_agent(db, token)).id == agent.id
        assert await q.authenticate_agent(db, token + "x") is None
        assert await q.authenticate_agent(db, "") is None


async def test_revoked_agent_is_rejected_and_releases_tasks(sm):
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, token = await _agent(db)
        await q.claim_task(db, agent, pdf_url_for=URL)
        assert await q.revoke_agent(db, agent.id) is True
        await db.commit()
        assert await q.authenticate_agent(db, token) is None
        task = (await db.execute(select(DocumentOcrTask))).scalar_one()
        assert task.status == "pending" and task.agent_id is None


# ---------- аренда ----------

async def test_request_marks_document_awaiting(sm):
    async with sm() as db:
        doc = await _doc(db)
        task = await q.request_ocr(db, doc)
        assert doc.status == q.AWAITING_OCR and task.status == "pending"


async def test_claim_gives_short_link_and_leases_task(sm):
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        assert got["document_id"] == doc.id
        assert got["pdf_url"].startswith("https://s3.example/meridian/1/documents/scan.pdf")
        assert got["pages_done"] == []
        # в аренде — второй раз не выдаётся
        assert await q.claim_task(db, agent, pdf_url_for=URL) is None


async def test_expired_lease_goes_to_another_agent(sm):
    """Компьютер выключили посреди работы — задача освобождается сама."""
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        sleeping, _ = await _agent(db, "спит")
        awake, _ = await _agent(db, "работает")
        got = await q.claim_task(db, sleeping, pdf_url_for=URL)
        task = await db.get(DocumentOcrTask, got["task_id"])
        task.lease_until = datetime.utcnow() - timedelta(seconds=1)
        again = await q.claim_task(db, awake, pdf_url_for=URL)
        assert again["task_id"] == task.id and task.attempts == 2
        with pytest.raises(q.OcrQueueError, match="не арендована"):
            await q.submit_page(db, sleeping, task.id, page_number=1, pages_total=1, text=PAGE_1)


async def test_pages_resume_after_reboot(sm):
    """Готовые страницы не распознаются заново — агент получает их список."""
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        await q.submit_page(db, agent, got["task_id"], page_number=1, pages_total=2, text=PAGE_1)
        task = await db.get(DocumentOcrTask, got["task_id"])
        task.lease_until = datetime.utcnow() - timedelta(seconds=1)
        again = await q.claim_task(db, agent, pdf_url_for=URL)
        assert again["pages_done"] == [1]


async def test_page_submission_extends_lease_and_overwrites(sm):
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        task = await db.get(DocumentOcrTask, got["task_id"])
        task.lease_until = datetime.utcnow() + timedelta(seconds=5)
        assert await q.submit_page(db, agent, task.id, page_number=1, pages_total=2, text="черновик") == 1
        assert await q.submit_page(db, agent, task.id, page_number=1, pages_total=2, text=PAGE_1) == 1
        assert task.lease_until > datetime.utcnow() + timedelta(seconds=60)
        page = (await db.execute(select(DocumentOcrPage))).scalar_one()
        assert page.text == PAGE_1


@pytest.mark.parametrize("page,total,match", [
    (3, 2, "номер страницы"), (1, 10_000, "лимита"),
])
async def test_bad_page_numbers_are_refused(sm, page, total, match):
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        with pytest.raises(q.OcrQueueError, match=match):
            await q.submit_page(db, agent, got["task_id"], page_number=page, pages_total=total, text="x")


async def test_incomplete_document_cannot_be_completed(sm):
    """Частичный текст опаснее отсутствующего: подсказка не заметит пропавших пунктов."""
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        await q.submit_page(db, agent, got["task_id"], page_number=1, pages_total=2, text=PAGE_1)
        with pytest.raises(q.OcrQueueError, match="сдано 1 из 2"):
            await q.complete_task(db, agent, got["task_id"])


# ---------- сбои ----------

async def test_failure_returns_task_to_queue(sm):
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        await q.fail_task(db, agent, got["task_id"], "LM Studio не отвечает")
        task = await db.get(DocumentOcrTask, got["task_id"])
        assert task.status == "pending" and "LM Studio" in task.last_error
        assert doc.status == q.AWAITING_OCR


async def test_last_attempt_failure_marks_document_error(sm, monkeypatch):
    monkeypatch.setattr(get_settings(), "ocr_agent_max_attempts", 1)
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        await q.fail_task(db, agent, got["task_id"], "модель не загружена")
        task = await db.get(DocumentOcrTask, got["task_id"])
        assert task.status == "failed"
        assert doc.status == "error" and "модель не загружена" in doc.processing_error


async def test_abandoned_task_fails_after_last_attempt(sm, monkeypatch):
    """Компьютер каждый раз выключается посреди работы — документ не висит вечно."""
    monkeypatch.setattr(get_settings(), "ocr_agent_max_attempts", 1)
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        task = await db.get(DocumentOcrTask, got["task_id"])
        task.lease_until = datetime.utcnow() - timedelta(seconds=1)
        assert await q.claim_task(db, agent, pdf_url_for=URL) is None
        assert task.status == "failed" and doc.status == "error"


async def test_rerequest_clears_previous_pages(sm):
    async with sm() as db:
        doc = await _doc(db)
        await q.request_ocr(db, doc)
        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        await q.submit_page(db, agent, got["task_id"], page_number=1, pages_total=1, text=PAGE_1)
        await q.request_ocr(db, doc)
        assert (await db.execute(select(func.count()).select_from(DocumentOcrPage))).scalar_one() == 0


# ---------- обработка документа целиком ----------

async def test_scan_goes_to_queue_then_becomes_searchable(sm, monkeypatch):
    """Сквозной путь: битый скан → очередь → агент сдаёт страницы → документ готов с текстом."""
    downloads = []

    async def download(key, dest):
        downloads.append(key)
        open(dest, "wb").close()

    async def put(key, data, content_type="text/plain"):
        return None

    monkeypatch.setattr(s3mod, "download_to", download)
    monkeypatch.setattr(s3mod, "put_bytes", put)
    monkeypatch.setattr(dp, "_extract_segments",
                        lambda path, ext: ([{"text": BROKEN, "page_number": 1, "sheet_name": None}], 2, None))

    async with sm() as db:
        doc = await _doc(db)
        await db.commit()
        doc_id = doc.id

    await dp.handle_document_process({"document_id": doc_id})
    async with sm() as db:
        doc = await db.get(DocumentRecord, doc_id)
        assert doc.status == q.AWAITING_OCR and doc.processing_error is None

        agent, _ = await _agent(db)
        got = await q.claim_task(db, agent, pdf_url_for=URL)
        await q.submit_page(db, agent, got["task_id"], page_number=2, pages_total=2, text=PAGE_2)
        await q.submit_page(db, agent, got["task_id"], page_number=1, pages_total=2, text=PAGE_1)
        await q.complete_task(db, agent, got["task_id"])
        await db.commit()
        job = (await db.execute(select(Job).where(Job.type == "document_process"))).scalars().all()
        assert job and job[-1].payload == {"document_id": doc_id}

    await dp.handle_document_process({"document_id": doc_id})
    async with sm() as db:
        doc = await db.get(DocumentRecord, doc_id)
        assert doc.status == "ready"
        assert '"ocr"' in doc.summary_json
        chunks = (await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                                   .order_by(DocumentChunk.chunk_index))).scalars().all()
        text = " ".join(c.text for c in chunks)
        assert "сорок пять" in text and "неустойку" in text
        assert [c.page_number for c in chunks] == [1, 2]
    # распознанный документ заново из хранилища не качается
    assert len(downloads) == 1


async def test_ocr_disabled_keeps_honest_error(sm, monkeypatch):
    monkeypatch.setattr(get_settings(), "document_ocr_enabled", False)

    async def download(key, dest):
        open(dest, "wb").close()

    monkeypatch.setattr(s3mod, "download_to", download)
    monkeypatch.setattr(dp, "_extract_segments", lambda path, ext: ([], 0, None))
    async with sm() as db:
        doc = await _doc(db)
        await db.commit()
        doc_id = doc.id
    await dp.handle_document_process({"document_id": doc_id})
    async with sm() as db:
        doc = await db.get(DocumentRecord, doc_id)
        assert doc.status == "error" and doc.processing_error == dp.EMPTY_TEXT_MESSAGE


async def test_huge_scan_is_not_queued(sm, monkeypatch):
    monkeypatch.setattr(get_settings(), "document_ocr_max_pages", 10)

    async def download(key, dest):
        open(dest, "wb").close()

    monkeypatch.setattr(s3mod, "download_to", download)
    monkeypatch.setattr(dp, "_extract_segments",
                        lambda path, ext: ([{"text": BROKEN, "page_number": 1, "sheet_name": None}], 400, None))
    async with sm() as db:
        doc = await _doc(db)
        await db.commit()
        doc_id = doc.id
    await dp.handle_document_process({"document_id": doc_id})
    async with sm() as db:
        doc = await db.get(DocumentRecord, doc_id)
        assert doc.status == "error" and "400 стр." in doc.processing_error


# ---------- ручки агента ----------

async def test_agent_api_requires_token_and_serves_claim(sm, monkeypatch):
    from app.main import app

    async def _db():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(s3mod, "presign_get", lambda key, ttl=None, **kw: URL(key))
    try:
        async with sm() as db:
            doc = await _doc(db)
            await q.request_ocr(db, doc)
            _, token = await _agent(db)
            await db.commit()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/ocr-agent/claim", json={})
            assert r.status_code == 401
            r = await client.post("/api/ocr-agent/claim", json={"model": "chandra-ocr-2"},
                                  headers={"Authorization": "Bearer wrong"})
            assert r.status_code == 401

            auth = {"Authorization": f"Bearer {token}"}
            r = await client.post("/api/ocr-agent/claim", json={"model": "chandra-ocr-2",
                                                                "agent_version": "1.0"}, headers=auth)
            assert r.status_code == 200
            task = r.json()["task"]
            assert task["file_name"] == "Договор ГП.pdf"

            r = await client.post(f"/api/ocr-agent/tasks/{task['task_id']}/pages", headers=auth,
                                  json={"page_number": 1, "pages_total": 1, "text": PAGE_1})
            assert r.status_code == 200 and r.json()["pages_done"] == 1
            r = await client.post(f"/api/ocr-agent/tasks/{task['task_id']}/complete", headers=auth)
            assert r.status_code == 200
            r = await client.post(f"/api/ocr-agent/tasks/{task['task_id']}/complete", headers=auth)
            assert r.status_code == 409  # уже не в аренде

        async with sm() as db:
            agent = (await db.execute(select(OcrAgent))).scalar_one()
            assert agent.model == "chandra-ocr-2" and agent.last_seen_at is not None
            status = await q.queue_status(db)
            assert status["done"] == 1 and status["agents"][0]["online"] is True
    finally:
        app.dependency_overrides.clear()
