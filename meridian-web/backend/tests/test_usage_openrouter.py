# -*- coding: utf-8 -*-
"""GET /api/usage/openrouter (только админ): математика, кэш, 404 без ключа, 502 без утечки ключа, 403/401, фолбэк /credits → /key."""

import httpx
import pytest
import pytest_asyncio

from app.api import usage as usage_api
from app.auth.dependencies import get_current_user
from app.main import app
from app.models.user import User

RAW = {"total": 50.0, "used": 12.3456}
ADMIN = User(id=1, email="a@test.local", role="admin")


@pytest_asyncio.fixture
async def client(monkeypatch):
    usage_api._reset_cache()
    calls: list[str] = []

    async def _keys() -> dict:
        return {"openrouter": "sk-or-test-key"}

    async def _fetch(api_key: str, proxy: str) -> dict:
        calls.append(api_key)
        return RAW

    monkeypatch.setattr(usage_api, "load_api_keys", _keys)
    monkeypatch.setattr(usage_api, "_fetch_openrouter_credits", _fetch)
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.calls = calls  # type: ignore[attr-defined]
            yield c
    finally:
        app.dependency_overrides.clear()
        usage_api._reset_cache()


def test_payload_math():
    assert usage_api._build_openrouter_payload(RAW) == {
        "total": 50.0, "used": 12.35, "remaining": 37.65, "percent_used": 25,
    }


def test_payload_total_none():
    p = usage_api._build_openrouter_payload({"total": None, "used": 3.0})
    assert p == {"total": None, "used": 3.0, "remaining": None, "percent_used": 0}


def test_payload_total_zero():
    assert usage_api._build_openrouter_payload({"total": 0.0, "used": 0.0})["percent_used"] == 0


@pytest.mark.asyncio
async def test_endpoint_payload(client):
    r = await client.get("/api/usage/openrouter")
    assert r.status_code == 200
    assert r.json()["remaining"] == 37.65


@pytest.mark.asyncio
async def test_cache(client):
    await client.get("/api/usage/openrouter")
    await client.get("/api/usage/openrouter")
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_no_key_404(client, monkeypatch):
    async def _no_keys() -> dict:
        return {}

    monkeypatch.setattr(usage_api, "load_api_keys", _no_keys)
    r = await client.get("/api/usage/openrouter")
    assert r.status_code == 404
    assert r.json() == {"detail": "нет ключа OpenRouter"}


@pytest.mark.asyncio
async def test_upstream_error_502(client, monkeypatch):
    async def _boom(api_key, proxy):
        raise httpx.ConnectError("sk-or-test-key refused")

    monkeypatch.setattr(usage_api, "_fetch_openrouter_credits", _boom)
    r = await client.get("/api/usage/openrouter")
    assert r.status_code == 502
    assert "sk-or-test-key" not in r.text


@pytest.mark.asyncio
async def test_non_admin_403(client):
    app.dependency_overrides[get_current_user] = lambda: User(id=2, email="u@test.local", role="user")
    r = await client.get("/api/usage/openrouter")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_401():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/usage/openrouter")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_fetch_credits_ok():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/credits"
        assert req.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"data": {"total_credits": 50, "total_usage": 12.5}})

    raw = await usage_api._fetch_openrouter_credits("k", "", httpx.MockTransport(handler))
    assert raw == {"total": 50.0, "used": 12.5}


@pytest.mark.asyncio
async def test_fetch_fallback_to_key_on_403():
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path == "/api/v1/credits":
            return httpx.Response(403, json={"error": "forbidden"})
        return httpx.Response(200, json={"data": {"usage": 4.0, "limit": 20.0, "limit_remaining": 16.0}})

    raw = await usage_api._fetch_openrouter_credits("k", "", httpx.MockTransport(handler))
    assert paths == ["/api/v1/credits", "/api/v1/key"]
    assert raw == {"total": 20.0, "used": 4.0}


@pytest.mark.asyncio
async def test_fetch_fallback_key_without_limit():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/credits":
            return httpx.Response(401)
        return httpx.Response(200, json={"data": {"usage": 4.0, "limit": None, "limit_remaining": None}})

    raw = await usage_api._fetch_openrouter_credits("k", "", httpx.MockTransport(handler))
    assert raw == {"total": None, "used": 4.0}
