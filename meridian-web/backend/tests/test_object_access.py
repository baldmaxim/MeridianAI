# -*- coding: utf-8 -*-
"""Ручная выдача доступа к проектам: матрица прав, записи без объекта, дедуп, заявки, админ-API."""

from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.service import create_access_token
from app.database import Base, get_db
from app.models.directory import Customer, ProjectObject
from app.models.document import DocumentRecord
from app.models.meeting import MeetingSession
from app.models.object_access import ObjectAccessRequest, UserCustomerAccess, UserObjectAccess
from app.models.user import User
from app.ratelimit import limiter
from app.services.access import user_can_access_meeting
from app.services.desktop_devices import enroll_device
from app.services.previous_meeting_context import get_context_candidates

# ключ пользователя -> (role, all_objects_access)
USERS = {
    "nobody": ("user", False),
    "obj": ("user", False),     # грант объекта O1a
    "cust": ("user", False),    # грант заказчика C1
    "all": ("user", True),      # «все проекты»
    "admin": ("admin", False),
}
# что должен видеть каждый: объекты / встречи / документы (ключи сценария)
EXPECTED = {
    "nobody": ([], ["free"], ["free"]),
    "obj": (["o1a"], ["o1a"], ["o1a"]),
    "cust": (["o1a", "o1b"], ["o1a", "o1b"], ["o1a", "o1b"]),
    "all": (["o1a", "o1b", "o2"], ["o1a", "o1b", "o2", "free"], ["o1a", "o1b", "o2", "free"]),
    "admin": (["o1a", "o1b", "o2"], ["o1a", "o1b", "o2", "free"], ["o1a", "o1b", "o2", "free"]),
}


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
async def client(sm):
    from app.main import app

    async def _db():
        async with sm() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    limiter.reset()
    app.dependency_overrides[get_db] = _db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        limiter.reset()


@pytest_asyncio.fixture
async def world(sm):
    """Заказчики C1 (O1a, O1b) и C2 (O2); по встрече и документу на объект + «свободные» записи nobody."""
    async with sm() as db:
        users = {}
        for key, (role, all_access) in USERS.items():
            u = User(email=f"{key}@t.local", password_hash="x", role=role,
                     is_active=True, all_objects_access=all_access, display_name=key)
            db.add(u)
            users[key] = u
        await db.flush()
        c1 = Customer(owner_user_id=users["all"].id, name="Acme")
        c2 = Customer(owner_user_id=users["all"].id, name="Beta")
        db.add_all([c1, c2])
        await db.flush()
        objs = {}
        for key, cust, name in (("o1a", c1, "Alpha-1"), ("o1b", c1, "Bravo-1"), ("o2", c2, "Charlie-2")):
            o = ProjectObject(owner_user_id=users["all"].id, customer_id=cust.id, name=name)
            db.add(o)
            objs[key] = o
        await db.flush()
        db.add(UserObjectAccess(user_id=users["obj"].id, object_id=objs["o1a"].id))
        db.add(UserCustomerAccess(user_id=users["cust"].id, customer_id=c1.id))

        meetings, docs = {}, {}
        for key in ("o1a", "o1b", "o2", "free"):
            obj = objs.get(key)
            author = users["nobody"] if key == "free" else users["all"]
            m = MeetingSession(
                user_id=author.id, created_by_user_id=author.id, title=f"M-{key}",
                started_at=datetime(2026, 11, 1, 9, 0), is_active=False,
                finalization_status="completed",
                object_id=obj.id if obj else None, customer_id=obj.customer_id if obj else None,
            )
            d = DocumentRecord(
                owner_user_id=author.id, created_by_user_id=author.id, original_name=f"{key}.pdf",
                file_ext="pdf", status="ready",
                object_id=obj.id if obj else None, customer_id=obj.customer_id if obj else None,
            )
            db.add_all([m, d])
            meetings[key], docs[key] = m, d
        await db.commit()
        return {
            "users": {k: u.id for k, u in users.items()},
            "roles": {k: u.role for k, u in users.items()},
            "objects": {k: o.id for k, o in objs.items()},
            "customers": {"c1": c1.id, "c2": c2.id},
            "meetings": {k: m.id for k, m in meetings.items()},
            "docs": {k: d.id for k, d in docs.items()},
        }


def _h(world, key):
    token = create_access_token(world["users"][key], world["roles"][key], 0)
    return {"Authorization": f"Bearer {token}"}


def _ids(world, group, keys):
    return sorted(world[group][k] for k in keys)


# ── матрица ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("who", list(USERS))
async def test_objects_list_and_get(client, world, who):
    exp_objects, _, _ = EXPECTED[who]
    r = await client.get("/api/objects", headers=_h(world, who))
    assert r.status_code == 200
    assert sorted(o["id"] for o in r.json()) == _ids(world, "objects", exp_objects)
    for key, oid in world["objects"].items():
        got = await client.get(f"/api/objects/{oid}", headers=_h(world, who))
        assert got.status_code == (200 if key in exp_objects else 404), (who, key)
        if key not in exp_objects:
            put = await client.put(f"/api/objects/{oid}", json={"notes": "x"}, headers=_h(world, who))
            assert put.status_code == 404, (who, key)
            dele = await client.delete(f"/api/objects/{oid}", headers=_h(world, who))
            assert dele.status_code == 404, (who, key)


@pytest.mark.parametrize("who", list(USERS))
async def test_meetings_list_and_get(client, world, who):
    _, exp_meetings, _ = EXPECTED[who]
    r = await client.get("/api/meetings", headers=_h(world, who))
    assert r.status_code == 200
    assert sorted(m["id"] for m in r.json()) == _ids(world, "meetings", exp_meetings)
    for key, mid in world["meetings"].items():
        got = await client.get(f"/api/meetings/{mid}", headers=_h(world, who))
        assert (got.status_code == 200) == (key in exp_meetings), (who, key, got.status_code)


@pytest.mark.parametrize("who", list(USERS))
async def test_documents_list_and_get(client, world, who):
    _, _, exp_docs = EXPECTED[who]
    r = await client.get("/api/documents", headers=_h(world, who))
    assert r.status_code == 200
    assert sorted(d["id"] for d in r.json()) == _ids(world, "docs", exp_docs)
    for key, did in world["docs"].items():
        got = await client.get(f"/api/documents/{did}", headers=_h(world, who))
        assert (got.status_code == 200) == (key in exp_docs), (who, key, got.status_code)


@pytest.mark.parametrize("who", list(USERS))
async def test_desktop_projects_and_library(sm, client, world, who):
    exp_objects, exp_meetings, _ = EXPECTED[who]
    async with sm() as db:
        _, token = await enroll_device(db, world["users"][who], "ПК", "windows", "0.1.0")
        await db.commit()
    h = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/desktop/projects", headers=h)
    assert r.status_code == 200
    seen = sorted(o["id"] for c in r.json() for o in c["objects"])
    assert seen == _ids(world, "objects", exp_objects)
    customer_names = {c["name"] for c in r.json()}
    if who == "nobody":
        assert customer_names == set()
    if who == "obj":
        assert customer_names == {"Acme"}  # заказчик виден по видимому объекту, без чужих объектов

    r = await client.get("/api/desktop/library", headers=h)
    assert r.status_code == 200
    assert sorted(m["meeting_id"] for m in r.json()) == _ids(world, "meetings", exp_meetings)


@pytest.mark.parametrize("who", list(USERS))
async def test_ws_check_user_can_access_meeting(sm, world, who):
    _, exp_meetings, _ = EXPECTED[who]
    async with sm() as db:
        for key, mid in world["meetings"].items():
            assert await user_can_access_meeting(db, world["users"][who], mid) == (key in exp_meetings)


async def test_previous_context_excludes_invisible_object_of_same_customer(sm, world):
    cur = world["meetings"]["o1a"]
    async with sm() as db:
        obj_user = await get_context_candidates(db, world["users"]["obj"], cur,
                                                customer_id=world["customers"]["c1"])
        cust_user = await get_context_candidates(db, world["users"]["cust"], cur,
                                                 customer_id=world["customers"]["c1"])
    assert [c.meeting_id for c in obj_user] == []                       # O1b невидим, O1a — текущая
    assert [c.meeting_id for c in cust_user] == [world["meetings"]["o1b"]]


async def test_letters_search_scoped_to_visible_projects(sm, client, world, monkeypatch):
    """Без project_id не-has_all ищет только по payhub-проектам видимых объектов."""
    from app.api import letters as letters_api

    async with sm() as db:
        for key, pid in (("o1a", 101), ("o1b", 102), ("o2", 103)):
            obj = await db.get(ProjectObject, world["objects"][key])
            obj.payhub_project_id = pid
        await db.commit()

    called: list[int | None] = []

    async def _search(query, k=8, project_id=None):
        called.append(project_id)
        return []

    monkeypatch.setattr(letters_api, "search_letters", _search)
    s = letters_api.get_settings()
    monkeypatch.setattr(type(s), "letters_rag_effective_enabled", property(lambda self: True))

    r = await client.post("/api/letters/search", json={"query": "бетон"}, headers=_h(world, "obj"))
    assert r.status_code == 200 and sorted(called) == [101]
    called.clear()
    r = await client.post("/api/letters/search", json={"query": "бетон", "project_id": 103},
                          headers=_h(world, "obj"))
    assert r.status_code == 200 and r.json() == [] and called == []   # чужой проект
    r = await client.post("/api/letters/search", json={"query": "бетон"}, headers=_h(world, "nobody"))
    assert r.status_code == 200 and r.json() == [] and called == []
    r = await client.post("/api/letters/search", json={"query": "бетон"}, headers=_h(world, "all"))
    assert r.status_code == 200 and called == [None]


# ── записи без объекта ────────────────────────────────────────────────────


async def test_record_without_object_visible_to_author_only(client, world):
    free_m, free_d = world["meetings"]["free"], world["docs"]["free"]
    ok = await client.get(f"/api/meetings/{free_m}", headers=_h(world, "nobody"))
    assert ok.status_code == 200
    for who in ("obj", "cust"):
        assert (await client.get(f"/api/meetings/{free_m}", headers=_h(world, who))).status_code != 200
        assert (await client.get(f"/api/documents/{free_d}", headers=_h(world, who))).status_code != 200
    # автор объектной встречи без доступа к объекту её не видит (авторство не даёт доступа)
    assert (await client.get(f"/api/meetings/{world['meetings']['o2']}",
                             headers=_h(world, "nobody"))).status_code != 200


async def test_delete_and_participants_require_meeting_access(client, world):
    mid = world["meetings"]["o2"]
    h = _h(world, "obj")
    assert (await client.delete(f"/api/meetings/{mid}", headers=h)).status_code == 403
    assert (await client.post(f"/api/meetings/{mid}/participants/{world['users']['obj']}",
                              headers=h)).status_code == 403
    assert (await client.delete(f"/api/meetings/{mid}/participants/{world['users']['obj']}",
                                headers=h)).status_code == 403
    assert (await client.delete(f"/api/meetings/{mid}", headers=_h(world, "all"))).status_code == 200


async def test_author_loses_object_meeting_after_revoke(sm, client, world):
    async with sm() as db:
        m = await db.get(MeetingSession, world["meetings"]["o1a"])
        m.user_id = m.created_by_user_id = world["users"]["obj"]
        await db.commit()
    h = _h(world, "obj")
    assert (await client.get(f"/api/meetings/{world['meetings']['o1a']}", headers=h)).status_code == 200
    async with sm() as db:
        grant = await db.get(UserObjectAccess, (world["users"]["obj"], world["objects"]["o1a"]))
        await db.delete(grant)
        await db.commit()
    assert (await client.get(f"/api/meetings/{world['meetings']['o1a']}", headers=h)).status_code != 200


# ── создание объекта: дубли и грант создателю ─────────────────────────────


def _create(client, world, who, **body):
    payload = {"customer_name": "Acme", "name": "Новый"}
    payload.update(body)
    return client.post("/api/objects", json=payload, headers=_h(world, who))


async def test_create_object_grants_creator(sm, client, world):
    r = await _create(client, world, "nobody", name="Delta-9", customer_name="Gamma")
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    async with sm() as db:
        assert await db.get(UserObjectAccess, (world["users"]["nobody"], oid)) is not None
    assert (await client.get(f"/api/objects/{oid}", headers=_h(world, "nobody"))).status_code == 200
    # has_all грант не получает
    r2 = await _create(client, world, "all", name="Delta-10", customer_name="Gamma")
    assert r2.status_code == 200
    async with sm() as db:
        assert await db.get(UserObjectAccess, (world["users"]["all"], r2.json()["id"])) is None


async def test_duplicate_exact_is_409_even_with_force_for_user(client, world):
    for force in (False, True):
        r = await _create(client, world, "obj", name='ЖК «Alpha-1»', force=force)
        assert r.status_code == 409
        d = r.json()["detail"]
        assert d["code"] == "duplicate_object" and d["exact"] is True
        assert d["candidates"] == [{
            "id": world["objects"]["o1a"], "name": "Alpha-1", "customer_name": "Acme",
            "has_access": True,
        }]


async def test_duplicate_candidates_reveal_no_extra_fields_and_has_access_per_user(client, world):
    r = await _create(client, world, "obj", name="alpha 1")
    assert r.status_code == 409
    r = await _create(client, world, "nobody", name="Bravo-1")
    cand = r.json()["detail"]["candidates"][0]
    assert set(cand) == {"id", "name", "customer_name", "has_access"}
    assert cand["has_access"] is False


async def test_duplicate_fuzzy_needs_force(sm, client, world):
    # то же имя у другого заказчика — нечёткое совпадение
    r = await _create(client, world, "nobody", name="Alpha-1", customer_name="Other")
    assert r.status_code == 409
    assert r.json()["detail"]["exact"] is False
    async with sm() as db:  # заказчик 409-запросом не создаётся
        assert (await db.execute(select(Customer).where(Customer.name == "Other"))).first() is None
    r = await _create(client, world, "nobody", name="Alpha-1", customer_name="Other", force=True)
    assert r.status_code == 200


async def test_duplicate_by_address_and_containment(client, world):
    r = await _create(client, world, "all", name="Совсем другое", customer_name="Other",
                      address="ул. Ленина, 1")
    assert r.status_code == 200  # адреса ещё нет
    r = await _create(client, world, "all", name="Иначе", customer_name="Other2", address="Ул Ленина  1")
    assert r.status_code == 409 and r.json()["detail"]["exact"] is False
    r = await _create(client, world, "all", name="ЖК Alpha-1 Парк", customer_name="Other3")
    assert r.status_code == 409  # содержит имя существующего


async def test_duplicate_admin_exact_is_allowed(client, world):
    r = await _create(client, world, "admin", name="Alpha-1")
    assert r.status_code == 200


# ── заявки ────────────────────────────────────────────────────────────────


async def test_access_request_flow(sm, client, world):
    oid = world["objects"]["o2"]
    h = _h(world, "nobody")
    for _ in range(2):  # идемпотентно
        r = await client.post(f"/api/objects/{oid}/access-request", headers=h)
        assert r.status_code == 200 and r.json() == {"status": "pending"}
    async with sm() as db:
        assert len((await db.execute(select(ObjectAccessRequest))).scalars().all()) == 1
    assert (await client.get(f"/api/objects/{oid}", headers=h)).status_code == 404
    assert (await client.post("/api/objects/9999/access-request", headers=h)).status_code == 404
    # админ видит заявку; обычный пользователь — нет
    assert (await client.get("/api/admin/object-access-requests", headers=h)).status_code == 403
    r = await client.get("/api/admin/object-access-requests?status=pending", headers=_h(world, "admin"))
    row = r.json()[0]
    assert set(row) == {"id", "user_id", "user_email", "user_display_name", "object_id",
                        "object_name", "customer_name", "status", "created_at"}
    assert row["object_id"] == oid and row["customer_name"] == "Beta" and row["user_email"] == "nobody@t.local"
    ap = await client.post(f"/api/admin/object-access-requests/{row['id']}/approve",
                           headers=_h(world, "admin"))
    assert ap.json() == {"status": "approved"}
    assert (await client.get(f"/api/objects/{oid}", headers=h)).status_code == 200
    again = await client.post(f"/api/admin/object-access-requests/{row['id']}/reject",
                              headers=_h(world, "admin"))
    assert again.status_code == 409
    assert (await client.post(f"/api/objects/{oid}/access-request", headers=h)).json() == {
        "status": "already_granted"}
    assert (await client.get("/api/admin/object-access-requests", headers=_h(world, "admin"))).json() == []


async def test_access_request_reject(client, world):
    oid = world["objects"]["o1b"]
    h = _h(world, "obj")
    await client.post(f"/api/objects/{oid}/access-request", headers=h)
    row = (await client.get("/api/admin/object-access-requests", headers=_h(world, "admin"))).json()[0]
    r = await client.post(f"/api/admin/object-access-requests/{row['id']}/reject", headers=_h(world, "admin"))
    assert r.json() == {"status": "rejected"}
    assert (await client.get(f"/api/objects/{oid}", headers=h)).status_code == 404


# ── админ-API грантов ─────────────────────────────────────────────────────


async def test_put_object_access_replaces_grants(client, world):
    admin = _h(world, "admin")
    uid = world["users"]["nobody"]
    url = f"/api/admin/users/{uid}/object-access"
    assert (await client.get(url, headers=admin)).json() == {
        "all_objects": False, "customer_ids": [], "object_ids": []}

    body = {"all_objects": False, "customer_ids": [world["customers"]["c2"]],
            "object_ids": [world["objects"]["o1a"]]}
    r = await client.put(url, json=body, headers=admin)
    assert r.status_code == 200 and r.json() == body
    ids = sorted(o["id"] for o in (await client.get("/api/objects", headers=_h(world, "nobody"))).json())
    assert ids == sorted([world["objects"]["o1a"], world["objects"]["o2"]])

    body2 = {"all_objects": False, "customer_ids": [], "object_ids": [world["objects"]["o1b"]]}
    assert (await client.put(url, json=body2, headers=admin)).json() == body2
    ids = [o["id"] for o in (await client.get("/api/objects", headers=_h(world, "nobody"))).json()]
    assert ids == [world["objects"]["o1b"]]

    body3 = {"all_objects": True, "customer_ids": [], "object_ids": []}
    assert (await client.put(url, json=body3, headers=admin)).json() == body3
    assert len((await client.get("/api/objects", headers=_h(world, "nobody"))).json()) == 3


async def test_put_object_access_validation_and_rights(client, world):
    admin = _h(world, "admin")
    uid = world["users"]["nobody"]
    url = f"/api/admin/users/{uid}/object-access"
    bad = await client.put(url, json={"all_objects": False, "customer_ids": [], "object_ids": [9999]},
                           headers=admin)
    assert bad.status_code == 422
    bad = await client.put(url, json={"all_objects": False, "customer_ids": [9999], "object_ids": []},
                           headers=admin)
    assert bad.status_code == 422
    assert (await client.get("/api/admin/users/9999/object-access", headers=admin)).status_code == 404
    assert (await client.get(url, headers=_h(world, "obj"))).status_code == 403
    assert (await client.put(url, json={"all_objects": True}, headers=_h(world, "obj"))).status_code == 403


async def test_customers_visibility_and_mutation_rights(client, world):
    r = await client.get("/api/customers", headers=_h(world, "obj"))
    assert [c["name"] for c in r.json()] == ["Acme"]
    c2 = world["customers"]["c2"]
    assert (await client.get(f"/api/customers/{c2}", headers=_h(world, "obj"))).status_code == 404
    assert (await client.put(f"/api/customers/{c2}", json={"name": "X"},
                             headers=_h(world, "obj"))).status_code == 403
    assert (await client.delete(f"/api/customers/{c2}", headers=_h(world, "obj"))).status_code == 403
    assert (await client.put(f"/api/customers/{c2}", json={"name": "Beta2"},
                             headers=_h(world, "all"))).status_code == 200


# ── RAG-папки и батч → встреча ────────────────────────────────────────────


async def test_rag_folders_follow_object_access(client, world):
    o1a, o2 = world["objects"]["o1a"], world["objects"]["o2"]
    obj, nobody, admin = _h(world, "obj"), _h(world, "nobody"), _h(world, "admin")

    r = await client.post("/api/rag/folders", json={"title": "Папка O1a", "object_id": o1a}, headers=obj)
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    # чужой объект / невидимый заказчик → 403
    assert (await client.post("/api/rag/folders", json={"title": "x", "object_id": o2},
                              headers=obj)).status_code == 403
    assert (await client.post("/api/rag/folders", json={"title": "x", "customer_id": world["customers"]["c2"]},
                              headers=obj)).status_code == 403
    # свободная папка (без объекта) — только автору и has_all
    free = (await client.post("/api/rag/folders", json={"title": "Личная"}, headers=nobody)).json()["id"]

    ids = lambda resp: sorted(f["id"] for f in resp.json())  # noqa: E731
    assert ids(await client.get("/api/rag/folders", headers=obj)) == [fid]
    assert ids(await client.get("/api/rag/folders", headers=nobody)) == [free]
    assert ids(await client.get("/api/rag/folders", headers=admin)) == sorted([fid, free])
    assert (await client.get(f"/api/rag/folders/{fid}", headers=nobody)).status_code == 404
    assert (await client.patch(f"/api/rag/folders/{fid}", json={"title": "y"}, headers=nobody)).status_code == 404
    # привязать к встрече можно только видимую папку
    mid = world["meetings"]["o1a"]
    assert (await client.post(f"/api/meetings/{mid}/rag-folders", json={"folder_id": free},
                              headers=obj)).status_code == 404
    assert (await client.post(f"/api/meetings/{mid}/rag-folders", json={"folder_id": fid},
                              headers=obj)).status_code == 200


async def test_batch_to_meeting_checks_object_and_customer_access(sm, client, world):
    from app.models.batch_job import BatchJob

    async with sm() as db:
        job = BatchJob(user_id=world["users"]["nobody"], original_filename="a.wav", file_path="k",
                       status="done")
        db.add(job)
        await db.commit()
        jid = job.id
    h = _h(world, "nobody")
    url = f"/api/batch/jobs/{jid}/to-meeting"
    assert (await client.post(url, json={"object_id": world["objects"]["o2"]}, headers=h)).status_code == 403
    assert (await client.post(url, json={"object_id": 9999}, headers=h)).status_code == 404
    assert (await client.post(url, json={"customer_id": world["customers"]["c2"]}, headers=h)).status_code == 403
