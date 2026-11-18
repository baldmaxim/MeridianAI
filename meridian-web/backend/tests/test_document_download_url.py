"""GET /documents/{id}/download-url: 404 без файла/для удалённого, 503 без S3, 200 с presign_get."""

import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api import documents as documents_mod
from app.config import get_settings
from app.database import Base
from app.models.document import DocumentRecord
from app.models.file import FileRecord
from app.models.user import User
from app.services import s3 as s3mod


@pytest_asyncio.fixture
async def db():
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


async def _user(db) -> User:
    u = User(email="dl@t.local", password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    return u


async def _doc(db, user, *, file_status: str | None) -> DocumentRecord:
    file_id = None
    if file_status is not None:
        f = FileRecord(user_id=user.id, object_key="documents/1/a.pdf", original_name="a.pdf",
                       purpose="document", status=file_status)
        db.add(f)
        await db.flush()
        file_id = f.id
    d = DocumentRecord(owner_user_id=user.id, created_by_user_id=user.id, file_id=file_id,
                       original_name="Смета.pdf", file_ext="pdf", status="ready")
    db.add(d)
    await db.flush()
    return d


def _s3(monkeypatch, enabled: bool = True):
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: enabled))


async def _call(db, user, doc_id):
    return await documents_mod.get_document_download_url(doc_id, Response(), user=user, db=db)


async def test_unknown_document_404(db, monkeypatch):
    _s3(monkeypatch)
    user = await _user(db)
    with pytest.raises(HTTPException) as e:
        await _call(db, user, 999)
    assert e.value.status_code == 404


async def test_document_without_file_404(db, monkeypatch):
    _s3(monkeypatch)
    user = await _user(db)
    doc = await _doc(db, user, file_status=None)
    with pytest.raises(HTTPException) as e:
        await _call(db, user, doc.id)
    assert e.value.status_code == 404


async def test_deleted_file_404(db, monkeypatch):
    _s3(monkeypatch)
    user = await _user(db)
    doc = await _doc(db, user, file_status="deleted")
    with pytest.raises(HTTPException) as e:
        await _call(db, user, doc.id)
    assert e.value.status_code == 404


async def test_s3_disabled_503(db, monkeypatch):
    _s3(monkeypatch, enabled=False)
    user = await _user(db)
    doc = await _doc(db, user, file_status="active")
    with pytest.raises(HTTPException) as e:
        await _call(db, user, doc.id)
    assert e.value.status_code == 503


async def test_ok_returns_presigned_url(db, monkeypatch):
    _s3(monkeypatch)
    calls: list[tuple] = []

    def _fake(key, ttl=None, download_name=None, public=True):
        calls.append((key, download_name))
        return "http://fake-s3/get?sig=x"

    monkeypatch.setattr(s3mod, "presign_get", _fake)
    user = await _user(db)
    doc = await _doc(db, user, file_status="active")
    resp = await _call(db, user, doc.id)
    assert resp.url == "http://fake-s3/get?sig=x"
    assert calls == [("documents/1/a.pdf", "Смета.pdf")]
