"""Тесты документов на S3 + извлечение/чанкинг + retrieval (Этап 4).

S3 замокан (presign/head/download/put). Эндпоинты с commit — на отдельном SQLite-движке.
"""

import os
import shutil
import tempfile

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.user import User
from app.models.meeting import MeetingSession, MeetingDocumentRecord
from app.models.directory import Customer, ProjectObject
from app.models.document import DocumentRecord, DocumentChunk
from app.schemas.document import DocumentUploadSessionRequest
from app.services import s3 as s3mod
from app.services import document_processing as dp
from app.services.document_context import get_relevant_chunks_for_meeting, format_chunks_block
from app.api.documents import create_document_upload_session, confirm_document_upload
from app.api.history import attach_meeting_document, list_meeting_documents


# ---------- helpers ----------

async def _mk_user(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _mk_meeting(db, owner, object_id=None):
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=True,
                       status="active", object_id=object_id)
    db.add(m)
    await db.flush()
    await db.refresh(m)
    return m


async def _mk_document(db, owner, status="ready", object_id=None, ext=".txt"):
    d = DocumentRecord(
        owner_user_id=owner.id, created_by_user_id=owner.id, object_id=object_id,
        original_name="doc" + ext, file_ext=ext, status=status, s3_key="k/doc" + ext,
    )
    db.add(d)
    await db.flush()
    await db.refresh(d)
    return d


async def _mk_chunk(db, doc, idx, text, sheet=None, page=None):
    c = DocumentChunk(document_id=doc.id, chunk_index=idx, text=text, sheet_name=sheet, page_number=page)
    db.add(c)
    await db.flush()
    return c


@pytest_asyncio.fixture
async def commit_db():
    """SQLite-движок без rollback-обёртки (для эндпоинтов, которые делают commit)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as s:
            yield s
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def sqlite_sm(monkeypatch):
    """SQLite sessionmaker + патч async_session в document_processing (job-обработчик)."""
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


def _enable_s3(monkeypatch):
    monkeypatch.setattr(s3mod, "presign_put", lambda key, ttl=None: "http://fake-s3/put")


# ---------- 1–3: upload-session ----------

async def test_upload_session_rejects_unsupported_ext(commit_db, monkeypatch):
    _enable_s3(monkeypatch)
    owner = await _mk_user(commit_db, "doc-up1@test.local")
    with pytest.raises(HTTPException) as exc:
        await create_document_upload_session(
            DocumentUploadSessionRequest(filename="virus.exe", size_bytes=10),
            user=owner, db=commit_db,
        )
    assert exc.value.status_code == 400


async def test_upload_session_accepts_supported_exts(commit_db, monkeypatch):
    _enable_s3(monkeypatch)
    owner = await _mk_user(commit_db, "doc-up2@test.local")
    for fn in ("a.pdf", "b.docx", "c.xlsx", "d.txt", "e.md", "f.csv"):
        resp = await create_document_upload_session(
            DocumentUploadSessionRequest(filename=fn, size_bytes=10),
            user=owner, db=commit_db,
        )
        assert resp.document_id and resp.upload_url == "http://fake-s3/put"


async def test_upload_session_object_open_to_everyone(commit_db, monkeypatch):
    # Общая модель: объект виден всем — любой авторизованный может прикрепить документ.
    _enable_s3(monkeypatch)
    owner = await _mk_user(commit_db, "doc-owner@test.local")
    stranger = await _mk_user(commit_db, "doc-stranger@test.local")
    cust = Customer(owner_user_id=owner.id, name="C")
    commit_db.add(cust); await commit_db.flush(); await commit_db.refresh(cust)
    obj = ProjectObject(owner_user_id=owner.id, customer_id=cust.id, name="O")
    commit_db.add(obj); await commit_db.flush(); await commit_db.refresh(obj)
    resp = await create_document_upload_session(
        DocumentUploadSessionRequest(filename="a.pdf", size_bytes=10, object_id=obj.id),
        user=stranger, db=commit_db,
    )
    assert resp.document_id and resp.upload_url == "http://fake-s3/put"


# ---------- 4: confirm-upload ----------

async def test_confirm_upload_missing_object(commit_db, monkeypatch):
    _enable_s3(monkeypatch)

    async def _no_head(key):
        return None
    monkeypatch.setattr(s3mod, "head_object", _no_head)

    owner = await _mk_user(commit_db, "doc-conf@test.local")
    resp = await create_document_upload_session(
        DocumentUploadSessionRequest(filename="a.txt", size_bytes=10), user=owner, db=commit_db,
    )
    with pytest.raises(HTTPException) as exc:
        await confirm_document_upload(resp.document_id, user=owner, db=commit_db)
    assert exc.value.status_code == 400


# ---------- 5–6: document_process ----------

async def test_document_process_txt_creates_chunks(sqlite_sm, monkeypatch):
    sm = sqlite_sm
    async with sm() as db:
        owner = await _mk_user(db, "dp-txt@test.local")
        doc = await _mk_document(db, owner, status="uploaded", ext=".txt")
        await db.commit()
        doc_id = doc.id

    async def _dl(key, dest):
        with open(dest, "wb") as f:
            f.write(("цена договора составляет пять миллионов рублей. " * 50).encode("utf-8"))
    monkeypatch.setattr(s3mod, "download_to", _dl)
    async def _put(key, data, content_type="text/plain"):
        return None
    monkeypatch.setattr(s3mod, "put_bytes", _put)

    await dp.handle_document_process({"document_id": doc_id})

    async with sm() as db:
        doc = await db.get(DocumentRecord, doc_id)
        assert doc.status == "ready"
        cc = await db.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id))
        assert cc and cc >= 1


async def test_document_process_xlsx_sheet_metadata(sqlite_sm, monkeypatch):
    sm = sqlite_sm
    # подготовить реальный xlsx с двумя листами
    from openpyxl import Workbook
    tmp = tempfile.mkdtemp()
    xlsx_path = os.path.join(tmp, "book.xlsx")
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Смета"
    ws1.append(["Позиция", "Цена"])
    ws1.append(["Бетон", 1000])
    ws2 = wb.create_sheet("ВОР")
    ws2.append(["Работа", "Объём"])
    ws2.append(["Кладка", 50])
    wb.save(xlsx_path)

    async with sm() as db:
        owner = await _mk_user(db, "dp-xlsx@test.local")
        doc = await _mk_document(db, owner, status="uploaded", ext=".xlsx")
        await db.commit()
        doc_id = doc.id

    async def _dl(key, dest):
        shutil.copy(xlsx_path, dest)
    monkeypatch.setattr(s3mod, "download_to", _dl)
    async def _put(key, data, content_type="text/plain"):
        return None
    monkeypatch.setattr(s3mod, "put_bytes", _put)

    await dp.handle_document_process({"document_id": doc_id})

    async with sm() as db:
        doc = await db.get(DocumentRecord, doc_id)
        assert doc.status == "ready"
        assert doc.sheet_count == 2
        sheets = (await db.execute(select(DocumentChunk.sheet_name).where(DocumentChunk.document_id == doc_id))).scalars().all()
        assert any(s in ("Смета", "ВОР") for s in sheets)
    shutil.rmtree(tmp, ignore_errors=True)


# ---------- 7–9: attach to meeting ----------

async def test_attach_meeting_open_to_everyone(db):
    # Общая модель: любой авторизованный может прикрепить документ к встрече.
    owner = await _mk_user(db, "att-owner@test.local")
    stranger = await _mk_user(db, "att-stranger@test.local")
    meeting = await _mk_meeting(db, owner)
    doc = await _mk_document(db, owner)
    res = await attach_meeting_document(meeting.id, doc.id, user=stranger, db=db)
    assert res.document_id == doc.id


async def test_attach_document_open_to_everyone(db):
    # Общая модель: чужой документ доступен — прикрепление к встрече разрешено.
    owner = await _mk_user(db, "att-owner2@test.local")
    other = await _mk_user(db, "att-other@test.local")
    meeting = await _mk_meeting(db, owner)
    doc = await _mk_document(db, other)             # документ другого автора
    res = await attach_meeting_document(meeting.id, doc.id, user=owner, db=db)
    assert res.document_id == doc.id


async def test_meeting_documents_list(db):
    owner = await _mk_user(db, "att-list@test.local")
    meeting = await _mk_meeting(db, owner)
    doc = await _mk_document(db, owner, status="ready")
    await attach_meeting_document(meeting.id, doc.id, user=owner, db=db)
    items = await list_meeting_documents(meeting.id, user=owner, db=db)
    assert len(items) == 1
    assert items[0].document_id == doc.id


# ---------- 10–12: retrieval ----------

async def test_retrieval_only_included_ready(db):
    owner = await _mk_user(db, "ret-owner@test.local")
    meeting = await _mk_meeting(db, owner)

    d_ok = await _mk_document(db, owner, status="ready")
    d_excluded = await _mk_document(db, owner, status="ready")
    d_notready = await _mk_document(db, owner, status="processing")
    await _mk_chunk(db, d_ok, 0, "договор цена пять миллионов")
    await _mk_chunk(db, d_excluded, 0, "договор штраф просрочка")
    await _mk_chunk(db, d_notready, 0, "договор гарантия два года")

    db.add(MeetingDocumentRecord(session_id=meeting.id, document_id=d_ok.id, included=True, priority=100))
    db.add(MeetingDocumentRecord(session_id=meeting.id, document_id=d_excluded.id, included=False, priority=100))
    db.add(MeetingDocumentRecord(session_id=meeting.id, document_id=d_notready.id, included=True, priority=100))
    await db.flush()

    res = await get_relevant_chunks_for_meeting(db, meeting.id, "договор", limit=6)
    ids = {r["document_id"] for r in res}
    assert ids == {d_ok.id}  # только included + ready


async def test_retrieval_meeting_isolation(db):
    owner = await _mk_user(db, "ret-iso@test.local")
    meeting_a = await _mk_meeting(db, owner)
    meeting_b = await _mk_meeting(db, owner)
    doc = await _mk_document(db, owner, status="ready")
    await _mk_chunk(db, doc, 0, "договор цена объект")
    db.add(MeetingDocumentRecord(session_id=meeting_b.id, document_id=doc.id, included=True, priority=100))
    await db.flush()
    res = await get_relevant_chunks_for_meeting(db, meeting_a.id, "договор", limit=6)
    assert res == []  # документ привязан к meeting_b, не к meeting_a


def test_format_chunks_block_respects_max_chars():
    chunks = [
        {"document_id": 1, "document_name": "D", "chunk_id": i, "text": "x" * 5000,
         "page_number": None, "sheet_name": None, "score": 1.0}
        for i in range(5)
    ]
    block = format_chunks_block(chunks, max_chunks=6, max_chars=8000)
    assert "Релевантные фрагменты документов" in block
    assert len(block) <= 8000 + 300  # уважает лимит (+overhead заголовков)
