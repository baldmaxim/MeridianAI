"""API словаря названий для распознавания (asr_terms): создание, нормализация, права."""

import json

import httpx
import pytest_asyncio
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.database import Base, get_db
from app.models.role_page_access import RolePageAccess
from app.models.user import User

URL = "/api/asr-terms"


@pytest_asyncio.fixture
async def env():
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    users: dict[str, User] = {}
    async with sm() as s:
        for name, role in (("alice", "user"), ("bob", "user"), ("root", "admin"), ("guest", "guest")):
            u = User(email=f"{name}@t.local", password_hash="x", role=role, is_active=True)
            s.add(u)
            users[name] = u
        # роли user получают доступ к «Базе знаний»; у guest — только дефолт (без неё)
        s.add(RolePageAccess(role_name="user", allowed_pages=json.dumps(["objects", "batch", "knowledge"])))
        await s.commit()

    async def _db():
        async with sm() as s:
            yield s

    async def _cur(request: Request):
        return users[request.headers["x-user"]]

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _cur
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def _as(name: str) -> dict[str, str]:
    return {"x-user": name}


async def test_create_and_list(env):
    r = await env.post(URL, json={"term": "  ООО Ромашка ", "aliases": ["рамашка"]}, headers=_as("alice"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["term"] == "ООО Ромашка"
    assert body["aliases"] == ["рамашка"]
    assert body["is_common"] is False
    assert body["can_delete"] is True

    await env.post(URL, json={"term": "Альфа"}, headers=_as("alice"))
    items = (await env.get(URL, headers=_as("alice"))).json()
    assert [i["term"] for i in items] == ["Альфа", "ООО Ромашка"]
    assert (await env.get(URL, headers=_as("bob"))).json() == []


async def test_aliases_normalized(env):
    r = await env.post(URL, json={
        "term": "Иванов",
        "aliases": [" Иванав ", "", "иванав", "ИВАНОВ", "  ", "Ивонов"],
    }, headers=_as("alice"))
    assert r.status_code == 201, r.text
    assert r.json()["aliases"] == ["Иванав", "Ивонов"]


async def test_validation_422(env):
    for payload in (
        {"term": "   "},
        {"term": "я" * 301},
        {"term": "x", "aliases": ["а" * 101]},
        {"term": "x", "aliases": [f"v{i}" for i in range(21)]},
    ):
        r = await env.post(URL, json=payload, headers=_as("alice"))
        assert r.status_code == 422, payload


async def test_duplicate_409(env):
    assert (await env.post(URL, json={"term": "Ёлка"}, headers=_as("alice"))).status_code == 201
    r = await env.post(URL, json={"term": " елка "}, headers=_as("alice"))
    assert r.status_code == 409
    assert r.json()["detail"] == "Такое название уже есть"
    # у другого пользователя тот же термин допустим
    assert (await env.post(URL, json={"term": "Ёлка"}, headers=_as("bob"))).status_code == 201


async def test_common_forbidden_for_non_admin(env):
    r = await env.post(URL, json={"term": "Общий", "common": True}, headers=_as("alice"))
    assert r.status_code == 403


async def test_admin_common_visible_to_others(env):
    r = await env.post(URL, json={"term": "Общий", "common": True}, headers=_as("root"))
    assert r.status_code == 201
    assert r.json()["is_common"] is True
    item = (await env.get(URL, headers=_as("alice"))).json()[0]
    assert item["term"] == "Общий"
    assert item["is_common"] is True
    assert item["can_delete"] is False
    # дубль общего видимого термина у обычного пользователя
    assert (await env.post(URL, json={"term": "общий"}, headers=_as("alice"))).status_code == 409


async def test_delete_own(env):
    term_id = (await env.post(URL, json={"term": "Свой"}, headers=_as("alice"))).json()["id"]
    assert (await env.delete(f"{URL}/{term_id}", headers=_as("alice"))).status_code == 204
    assert (await env.get(URL, headers=_as("alice"))).json() == []


async def test_delete_foreign_404_and_common_403(env):
    own_id = (await env.post(URL, json={"term": "Чужой"}, headers=_as("alice"))).json()["id"]
    common_id = (await env.post(URL, json={"term": "Общий", "common": True}, headers=_as("root"))).json()["id"]

    assert (await env.delete(f"{URL}/{own_id}", headers=_as("bob"))).status_code == 404
    assert (await env.delete(f"{URL}/999999", headers=_as("bob"))).status_code == 404
    assert (await env.delete(f"{URL}/{common_id}", headers=_as("bob"))).status_code == 403

    assert (await env.delete(f"{URL}/{common_id}", headers=_as("root"))).status_code == 204


async def test_page_access_required(env):
    assert (await env.get(URL, headers=_as("guest"))).status_code == 403
