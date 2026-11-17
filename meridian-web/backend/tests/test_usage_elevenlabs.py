# -*- coding: utf-8 -*-
"""GET /api/usage/elevenlabs: поля, процент, кэш 120 с, нет ключа → 404, сбой апстрима → 502, без токена → 401."""

import httpx
import pytest
import pytest_asyncio

from app.api import usage as usage_api
from app.auth.dependencies import get_current_user
from app.main import app
from app.models.user import User

SUB = {"character_count": 6185, "character_limit": 131000, "next_character_count_reset_unix": 1764892800}


@pytest_asyncio.fixture
async def client(monkeypatch):
    usage_api._reset_cache()
    calls: list[str] = []

    async def _keys() -> dict:
        return {"elevenlabs": "xi-test-key"}

    async def _fetch(api_key: str, proxy: str) -> dict:
        calls.append(api_key)
        return SUB

    monkeypatch.setattr(usage_api, "load_api_keys", _keys)
    monkeypatch.setattr(usage_api, "_fetch_subscription", _fetch)
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="u@test.local", role="user")
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.calls = calls  # type: ignore[attr-defined]
            yield c
    finally:
        app.dependency_overrides.clear()
        usage_api._reset_cache()


@pytest.mark.asyncio
async def test_fields_and_percent(client):
    r = await client.get("/api/usage/elevenlabs")
    assert r.status_code == 200
    assert r.json() == {
        "used": 6185, "limit": 131000, "remaining": 124815, "percent_used": 5, "next_reset": "2025-12-05",
    }


@pytest.mark.asyncio
async def test_zero_limit(client, monkeypatch):
    async def _fetch(api_key, proxy):
        return {"character_count": 0, "character_limit": 0}

    monkeypatch.setattr(usage_api, "_fetch_subscription", _fetch)
    r = await client.get("/api/usage/elevenlabs")
    assert r.json()["percent_used"] == 0
    assert r.json()["next_reset"] is None


@pytest.mark.asyncio
async def test_cache(client):
    await client.get("/api/usage/elevenlabs")
    await client.get("/api/usage/elevenlabs")
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_no_key_404(client, monkeypatch):
    async def _no_keys() -> dict:
        return {}

    monkeypatch.setattr(usage_api, "load_api_keys", _no_keys)
    r = await client.get("/api/usage/elevenlabs")
    assert r.status_code == 404
    assert r.json() == {"detail": "нет ключа ElevenLabs"}


@pytest.mark.asyncio
async def test_upstream_error_502(client, monkeypatch):
    async def _boom(api_key, proxy):
        raise httpx.ConnectError("xi-test-key refused")

    monkeypatch.setattr(usage_api, "_fetch_subscription", _boom)
    r = await client.get("/api/usage/elevenlabs")
    assert r.status_code == 502
    assert "xi-test-key" not in r.text


@pytest.mark.asyncio
async def test_unauthenticated_401():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/usage/elevenlabs")
    assert r.status_code == 401
