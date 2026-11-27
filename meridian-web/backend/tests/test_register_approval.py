# -*- coding: utf-8 -*-
"""Регистрация: первый пользователь — admin с токеном, остальные ждут одобрения админом."""

import httpx
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.user import User
from app.ratelimit import limiter

PASSWORD = "password-1"


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

    async def _audit(event_type, actor_user_id=None, ip=None, **details):
        return None

    monkeypatch.setattr(admin_api, "audit", _audit)
    monkeypatch.setattr(auth_router, "audit", _audit)
    limiter.reset()
    app.dependency_overrides[get_db] = _db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        limiter.reset()


async def _register(client, email):
    return await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})


async def _login(client, email):
    return await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})


async def _user(sm, email) -> User:
    async with sm() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one()


async def test_first_user_is_admin_with_token(sm, client):
    r = await _register(client, "first@example.com")
    assert r.status_code == 200
    body = r.json()
    assert body["pending"] is False
    assert body["access_token"]
    u = await _user(sm, "first@example.com")
    assert u.role == "admin" and u.is_active is True


async def test_next_user_pending_without_token(sm, client):
    await _register(client, "first@example.com")
    r = await _register(client, "second@example.com")
    assert r.status_code == 200
    body = r.json()
    assert body["pending"] is True
    assert body["access_token"] is None
    u = await _user(sm, "second@example.com")
    assert u.role == "user" and u.is_active is False


async def test_pending_user_login_forbidden_until_approved(sm, client):
    admin_token = (await _register(client, "first@example.com")).json()["access_token"]
    await _register(client, "second@example.com")

    blocked = await _login(client, "second@example.com")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Account is deactivated"

    second = await _user(sm, "second@example.com")
    r = await client.put(
        f"/api/admin/users/{second.id}",
        json={"is_active": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True

    ok = await _login(client, "second@example.com")
    assert ok.status_code == 200
    assert ok.json()["access_token"]
