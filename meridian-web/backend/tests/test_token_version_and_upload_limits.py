# -*- coding: utf-8 -*-
"""Отзыв access-токенов (claim `tv` ↔ users.token_version) и потоковые лимиты загрузок."""

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.auth.service import create_access_token, hash_password
from app.database import Base, get_db
from app.models.user import User
from app.ratelimit import limiter


@pytest_asyncio.fixture
async def sm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(sm, monkeypatch):
    from app.api import admin as admin_api
    from app.auth import router as auth_router
    from app.main import app

    async def _db():
        async with sm() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    events: list[str] = []

    async def _audit(event_type, actor_user_id=None, ip=None, **details):
        events.append(event_type)

    monkeypatch.setattr(admin_api, "audit", _audit)
    monkeypatch.setattr(auth_router, "audit", _audit)
    limiter.reset()
    app.dependency_overrides[get_db] = _db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            c.audit_events = events  # type: ignore[attr-defined]
            yield c
    finally:
        app.dependency_overrides.clear()
        limiter.reset()


async def _user(sm, email="u@test.local", role="user", version=0) -> User:
    async with sm() as db:
        u = User(email=email, password_hash=hash_password("password-1"), role=role, token_version=version)
        db.add(u)
        await db.commit()
        return u


async def _version(sm, user_id: int) -> int:
    async with sm() as db:
        return (await db.get(User, user_id)).token_version


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _old_token(user: User) -> str:
    """Токен старого формата — без claim `tv`."""
    from jose import jwt
    from app.config import get_settings
    s = get_settings()
    return jwt.encode({"sub": str(user.id), "role": user.role}, s.jwt_secret, algorithm=s.jwt_algorithm)


# ---------- REST ----------

async def test_model_default_version_is_zero(sm):
    async with sm() as db:
        u = User(email="d@test.local", password_hash="x")
        db.add(u)
        await db.commit()
        assert u.token_version == 0


async def test_token_without_tv_works_while_version_zero(sm, client):
    u = await _user(sm)
    r = await client.get("/api/auth/me", headers=_auth(_old_token(u)))
    assert r.status_code == 200


async def test_matching_tv_works_and_stale_tv_rejected(sm, client):
    u = await _user(sm, version=2)
    ok = await client.get("/api/auth/me", headers=_auth(create_access_token(u.id, u.role, 2)))
    assert ok.status_code == 200
    stale = await client.get("/api/auth/me", headers=_auth(create_access_token(u.id, u.role, 1)))
    assert stale.status_code == 401
    # токен без claim == версия 0, а у пользователя уже 2
    assert (await client.get("/api/auth/me", headers=_auth(_old_token(u)))).status_code == 401


async def test_login_token_carries_current_version(sm, client):
    await _user(sm, email="l@example.com", version=3)
    r = await client.post("/api/auth/login", json={"email": "l@example.com", "password": "password-1"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert (await client.get("/api/auth/me", headers=_auth(token))).status_code == 200


async def test_logout_all_bumps_version_and_kills_tokens(sm, client):
    u = await _user(sm)
    token = create_access_token(u.id, u.role, 0)
    r = await client.post("/api/auth/logout-all", headers=_auth(token))
    assert r.status_code == 204 and r.content == b""
    assert await _version(sm, u.id) == 1
    assert "logout_all" in client.audit_events
    assert (await client.get("/api/auth/me", headers=_auth(token))).status_code == 401


async def test_admin_role_change_password_reset_and_deactivate_bump_version(sm, client):
    admin = await _user(sm, email="a@test.local", role="admin")
    target = await _user(sm, email="t@test.local")
    h = _auth(create_access_token(admin.id, admin.role, 0))
    url = f"/api/admin/users/{target.id}"

    assert (await client.put(url, json={"role": "admin"}, headers=h)).status_code == 200
    assert await _version(sm, target.id) == 1
    assert (await client.put(url, json={"password": "new-pass"}, headers=h)).status_code == 200
    assert await _version(sm, target.id) == 2
    assert (await client.put(url, json={"is_active": False}, headers=h)).status_code == 200
    assert await _version(sm, target.id) == 3
    # правка имени токены не отзывает
    assert (await client.put(url, json={"display_name": "Имя"}, headers=h)).status_code == 200
    assert await _version(sm, target.id) == 3


# ---------- WS ----------

async def test_ws_auth_rejects_stale_tv(sm, monkeypatch):
    from app.services import meeting_setup
    monkeypatch.setattr(meeting_setup, "async_session", sm)
    u = await _user(sm, version=1)
    assert await meeting_setup.authenticate_ws(create_access_token(u.id, u.role, 1)) is not None
    assert await meeting_setup.authenticate_ws(create_access_token(u.id, u.role, 0)) is None
    assert await meeting_setup.authenticate_ws(_old_token(u)) is None


async def test_ws_auth_old_token_ok_at_version_zero(sm, monkeypatch):
    from app.services import meeting_setup
    monkeypatch.setattr(meeting_setup, "async_session", sm)
    u = await _user(sm)
    assert await meeting_setup.authenticate_ws(_old_token(u)) is not None


# ---------- download ?token= ----------

async def test_download_rejects_stale_tv(sm, monkeypatch):
    from app.api import meetings as meetings_api
    monkeypatch.setattr(meetings_api, "async_session", sm)
    u = await _user(sm, version=1)

    with pytest.raises(HTTPException) as exc:
        await meetings_api.download_transcription(1, token=create_access_token(u.id, u.role, 0))
    assert exc.value.status_code == 401

    # актуальный токен проходит аутентификацию (дальше — 404: записи нет)
    with pytest.raises(HTTPException) as exc:
        await meetings_api.download_transcription(1, token=create_access_token(u.id, u.role, 1))
    assert exc.value.status_code == 404


# ---------- лимиты загрузок ----------

@pytest_asyncio.fixture
async def upload_client(sm):
    from app.main import app

    async def _db():
        async with sm() as s:
            yield s
            await s.commit()

    u = await _user(sm, email="up@test.local")

    async def _cur():
        return u

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _cur
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _files_under(path) -> list:
    return [p for p in path.rglob("*") if p.is_file()]


async def test_legacy_document_upload_over_limit_413_no_file_left(upload_client, tmp_path, monkeypatch):
    from app.api import documents as documents_api
    monkeypatch.setattr(documents_api, "get_settings",
                        lambda: SimpleNamespace(upload_dir=str(tmp_path), document_max_upload_mb=1))
    big = b"a" * (1024 * 1024 + 1)
    r = await upload_client.post("/api/documents/upload", files={"file": ("big.txt", big)},
                                 data={"doc_type": "other"})
    assert r.status_code == 413
    assert "слишком большой" in r.json()["detail"]
    assert _files_under(tmp_path) == []


async def test_legacy_document_upload_within_limit_passes_size_check(upload_client, tmp_path, monkeypatch):
    from app.api import documents as documents_api
    monkeypatch.setattr(documents_api, "get_settings",
                        lambda: SimpleNamespace(upload_dir=str(tmp_path), document_max_upload_mb=1))
    r = await upload_client.post("/api/documents/upload", files={"file": ("ok.txt", b"hello")},
                                 data={"doc_type": "other"})
    assert r.status_code != 413


async def test_batch_fallback_upload_over_limit_413_no_file_left(upload_client, tmp_path, monkeypatch):
    from app.api import batch as batch_api
    monkeypatch.setattr(batch_api, "get_settings", lambda: SimpleNamespace(upload_dir=str(tmp_path)))
    monkeypatch.setattr(batch_api, "MAX_FILE_SIZE", 2 * 1024 * 1024)
    big = b"a" * (2 * 1024 * 1024 + 1)
    r = await upload_client.post("/api/batch/upload", files={"file": ("a.mp3", big)})
    assert r.status_code == 413
    assert "слишком большой" in r.json()["detail"]
    assert _files_under(tmp_path) == []


async def test_batch_fallback_upload_within_limit_saves_size(upload_client, tmp_path, monkeypatch):
    from app.api import batch as batch_api
    monkeypatch.setattr(batch_api, "get_settings", lambda: SimpleNamespace(upload_dir=str(tmp_path)))
    monkeypatch.setattr(batch_api, "MAX_FILE_SIZE", 2 * 1024 * 1024)
    r = await upload_client.post("/api/batch/upload", files={"file": ("a.mp3", b"x" * 1500000)})
    assert r.status_code == 200, r.text
    assert r.json()["original_size"] == 1500000
    assert len(_files_under(tmp_path)) == 1
