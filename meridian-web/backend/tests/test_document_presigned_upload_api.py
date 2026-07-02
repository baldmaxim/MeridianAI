"""Этап 22: presigned-S3 document upload API — initiate (mode-aware) + confirm (HEAD-валидация).

Эндпоинты зовём напрямую (как test_stage4_documents), S3 замокан, SQLite commit-движок.
Проверяем: legacy-режим при выключенном S3, s3-режим, отклонение content-type/размера, HEAD на
confirm, permission-mismatch, отсутствие s3_key/URL в публичном ответе и безопасность логов.
"""

import logging

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base
from app.models.user import User
from app.models.document import DocumentRecord
from app.schemas.document import DocumentUploadSessionRequest, DocumentResponse
from app.services import s3 as s3mod
from app.services import document_storage as ds
from app.api import documents as documents_mod


@pytest_asyncio.fixture
async def commit_db():
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


async def _mk_user(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


def _req(**kw):
    return DocumentUploadSessionRequest(**kw)


def _enable_s3(monkeypatch):
    monkeypatch.setattr(ds, "is_enabled", lambda: True)
    monkeypatch.setattr(s3mod, "presign_put",
                        lambda key, ttl=None, sse=None, kms_key_id=None: "http://fake-s3/put")


# --- initiate: mode-aware ---

async def test_initiate_legacy_mode_when_disabled(commit_db, monkeypatch):
    monkeypatch.setattr(ds, "is_enabled", lambda: False)
    owner = await _mk_user(commit_db, "s3d-1@t.local")
    resp = await documents_mod.create_document_upload_session(
        _req(filename="a.pdf", size_bytes=10), user=owner, db=commit_db)
    assert resp.upload_mode == "legacy_multipart"
    assert resp.legacy_upload_url == "/api/documents/upload"
    assert resp.document_id is None and resp.upload_url is None
    assert await commit_db.scalar(select(func.count(DocumentRecord.id))) == 0  # записей нет


async def test_initiate_s3_mode_when_enabled(commit_db, monkeypatch):
    _enable_s3(monkeypatch)
    owner = await _mk_user(commit_db, "s3d-2@t.local")
    resp = await documents_mod.create_document_upload_session(
        _req(filename="c.pdf", content_type="application/pdf", size_bytes=100), user=owner, db=commit_db)
    assert resp.upload_mode == "s3_presigned"
    assert resp.upload_url == "http://fake-s3/put"
    assert resp.document_id and resp.file_id
    assert resp.max_upload_bytes and resp.max_upload_bytes > 0


async def test_initiate_invalid_content_type_rejected(commit_db, monkeypatch):
    _enable_s3(monkeypatch)
    owner = await _mk_user(commit_db, "s3d-3@t.local")
    with pytest.raises(HTTPException) as e:
        await documents_mod.create_document_upload_session(
            _req(filename="c.pdf", content_type="image/png", size_bytes=10), user=owner, db=commit_db)
    assert e.value.status_code == 400


async def test_initiate_too_large_rejected(commit_db, monkeypatch):
    _enable_s3(monkeypatch)
    monkeypatch.setattr(get_settings(), "document_s3_max_upload_bytes", 1000)
    owner = await _mk_user(commit_db, "s3d-4@t.local")
    with pytest.raises(HTTPException) as e:
        await documents_mod.create_document_upload_session(
            _req(filename="c.pdf", content_type="application/pdf", size_bytes=5000), user=owner, db=commit_db)
    assert e.value.status_code == 400


# --- confirm: HEAD + permission ---

async def test_confirm_rejects_when_head_missing(commit_db, monkeypatch):
    _enable_s3(monkeypatch)

    async def _no_head(key):
        return None
    monkeypatch.setattr(s3mod, "head_object", _no_head)

    owner = await _mk_user(commit_db, "s3d-5@t.local")
    resp = await documents_mod.create_document_upload_session(
        _req(filename="a.txt", size_bytes=10), user=owner, db=commit_db)
    with pytest.raises(HTTPException) as e:
        await documents_mod.confirm_document_upload(resp.document_id, user=owner, db=commit_db)
    assert e.value.status_code == 400


async def test_confirm_creates_and_enqueues(commit_db, monkeypatch):
    _enable_s3(monkeypatch)

    async def _head(key):
        return {"size": 123, "content_type": "application/pdf"}
    monkeypatch.setattr(s3mod, "head_object", _head)

    calls = []

    async def _enq(db, jtype, payload):
        calls.append((jtype, payload))
    monkeypatch.setattr(documents_mod, "enqueue", _enq)

    owner = await _mk_user(commit_db, "s3d-6@t.local")
    resp = await documents_mod.create_document_upload_session(
        _req(filename="a.pdf", content_type="application/pdf", size_bytes=123), user=owner, db=commit_db)
    conf = await documents_mod.confirm_document_upload(resp.document_id, user=owner, db=commit_db)
    assert conf.status == "uploaded"
    assert calls and calls[0][0] == "document_process" and calls[0][1]["document_id"] == resp.document_id
    doc = await commit_db.get(DocumentRecord, resp.document_id)
    assert doc.status == "uploaded" and doc.file_size == 123


async def test_confirm_validates_content_type_even_when_headcheck_flag_off(commit_db, monkeypatch):
    # Спека Этапа 22: content-type/размер валидируются на confirm ВСЕГДА при наличии meta,
    # даже если DOCUMENT_S3_COMPLETE_HEAD_CHECK_ENABLED=False (флаг смягчает только meta=None).
    _enable_s3(monkeypatch)
    monkeypatch.setattr(get_settings(), "document_s3_complete_head_check_enabled", False)

    async def _bad_head(key):
        return {"size": 10, "content_type": "image/png"}
    monkeypatch.setattr(s3mod, "head_object", _bad_head)

    owner = await _mk_user(commit_db, "s3d-8@t.local")
    resp = await documents_mod.create_document_upload_session(
        _req(filename="a.pdf", content_type="application/pdf", size_bytes=10), user=owner, db=commit_db)
    with pytest.raises(HTTPException) as e:
        await documents_mod.confirm_document_upload(resp.document_id, user=owner, db=commit_db)
    assert e.value.status_code == 400


async def test_initiate_sets_no_store_cache_header(commit_db, monkeypatch):
    from fastapi import Response
    _enable_s3(monkeypatch)
    owner = await _mk_user(commit_db, "s3d-10@t.local")
    resp_obj = Response()
    await documents_mod.create_document_upload_session(
        _req(filename="a.pdf", content_type="application/pdf", size_bytes=10),
        response=resp_obj, user=owner, db=commit_db)
    assert "no-store" in resp_obj.headers.get("cache-control", "")


async def test_confirm_permission_mismatch_rejected(commit_db, monkeypatch):
    _enable_s3(monkeypatch)

    async def _head(key):
        return {"size": 10, "content_type": "application/pdf"}
    monkeypatch.setattr(s3mod, "head_object", _head)

    owner = await _mk_user(commit_db, "s3d-7a@t.local")
    stranger = await _mk_user(commit_db, "s3d-7b@t.local")
    resp = await documents_mod.create_document_upload_session(
        _req(filename="a.pdf", content_type="application/pdf", size_bytes=10), user=owner, db=commit_db)
    with pytest.raises(HTTPException) as e:
        await documents_mod.confirm_document_upload(resp.document_id, user=stranger, db=commit_db)
    assert e.value.status_code == 404


# --- приватность ответа/логов ---

def test_document_response_hides_storage_pointers():
    fields = set(DocumentResponse.model_fields)
    assert "s3_key" not in fields and "s3_bucket" not in fields
    assert "upload_url" not in fields and "extracted_text_s3_key" not in fields


async def test_initiate_log_no_filename_or_presigned_url(commit_db, monkeypatch, caplog):
    _enable_s3(monkeypatch)
    owner = await _mk_user(commit_db, "s3d-9@t.local")
    secret_name = "СуперСекретныйКонтракт-2026.pdf"
    with caplog.at_level(logging.INFO, logger="meridian.documents"):
        resp = await documents_mod.create_document_upload_session(
            _req(filename=secret_name, content_type="application/pdf", size_bytes=10), user=owner, db=commit_db)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "[DocumentS3Upload] initiated" in text
    assert "СуперСекретныйКонтракт" not in text          # raw filename не логируется
    assert "http://fake-s3/put" not in text              # presigned URL не логируется
    assert resp.s3_key and resp.s3_key not in text        # object key не логируется (только hash-ref)
