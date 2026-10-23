"""Десктоп: документы встречи — загрузка (presigned S3), идемпотентное подтверждение,
список с унаследованными документами заказчика/объекта и включение/выключение."""

from sqlalchemy import func, select

from app.models.directory import Customer, ProjectObject
from app.models.document import DocumentRecord
from app.models.job import Job
from app.models.meeting import MeetingDocumentRecord
from app.services import document_storage
from app.services import s3 as s3mod

from .test_desktop_api import _bearer, _device, _jwt, _meeting, _user, client, sm  # noqa: F401


async def _customer_and_object(sm):
    async with sm() as db:
        cust = Customer(name="Заказчик")
        db.add(cust)
        await db.flush()
        obj = ProjectObject(customer_id=cust.id, name="Объект")
        db.add(obj)
        await db.commit()
        return cust.id, obj.id


def _enable_s3(monkeypatch):
    monkeypatch.setattr(document_storage, "is_enabled", lambda: True)
    monkeypatch.setattr(s3mod, "presign_put", lambda key, ttl=None, **kw: "https://s3.example/put?sig=x")


async def test_upload_session_without_s3_is_503(sm, client, monkeypatch):
    monkeypatch.setattr(document_storage, "is_enabled", lambda: False)
    token = await _device(sm, await _user(sm))
    mid = (await _meeting(client, token))["meeting_id"]
    r = await client.post("/api/desktop/documents/upload-session", headers=_bearer(token),
                          json={"filename": "d.pdf", "size": 100, "meeting_id": mid})
    assert r.status_code == 503
    async with sm() as db:
        assert (await db.execute(select(func.count(DocumentRecord.id)))).scalar() == 0


async def test_upload_session_takes_customer_and_object_from_meeting(sm, client, monkeypatch):
    _enable_s3(monkeypatch)
    cust_id, obj_id = await _customer_and_object(sm)
    token = await _device(sm, await _user(sm))
    mid = (await _meeting(client, token, customer_id=cust_id, object_id=obj_id))["meeting_id"]
    r = await client.post("/api/desktop/documents/upload-session", headers=_bearer(token),
                          json={"filename": "d.pdf", "size": 100, "mime_type": "application/pdf",
                                "meeting_id": mid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["upload_mode"] == "s3_presigned" and body["upload_url"].startswith("https://s3.example/")
    assert "no-store" in r.headers["cache-control"]
    async with sm() as db:
        doc = await db.get(DocumentRecord, body["document_id"])
        assert (doc.customer_id, doc.object_id, doc.status) == (cust_id, obj_id, "pending")


async def test_upload_session_foreign_meeting_is_404(sm, client, monkeypatch):
    _enable_s3(monkeypatch)
    owner_token = await _device(sm, await _user(sm, "a@t.local"))
    mid = (await _meeting(client, owner_token))["meeting_id"]
    stranger = await _device(sm, await _user(sm, "b@t.local"))
    r = await client.post("/api/desktop/documents/upload-session", headers=_bearer(stranger),
                          json={"filename": "d.pdf", "size": 100, "meeting_id": mid})
    assert r.status_code == 404


async def test_confirm_attaches_and_is_idempotent(sm, client, monkeypatch):
    _enable_s3(monkeypatch)
    heads = []

    async def _head(key):
        heads.append(key)
        return {"size": 100, "content_type": "application/pdf"}

    monkeypatch.setattr(s3mod, "head_object", _head)
    token = await _device(sm, await _user(sm))
    h = _bearer(token)
    mid = (await _meeting(client, token))["meeting_id"]
    up = await client.post("/api/desktop/documents/upload-session", headers=h,
                           json={"filename": "d.pdf", "size": 100, "mime_type": "application/pdf",
                                 "meeting_id": mid})
    doc_id = up.json()["document_id"]

    for _ in range(2):
        r = await client.post(f"/api/desktop/documents/{doc_id}/confirm", headers=h, json={"meeting_id": mid})
        assert r.status_code == 200, r.text
        assert r.json() == {"document_id": doc_id, "status": "uploaded"}

    assert len(heads) == 1  # второй вызов S3 не трогает
    async with sm() as db:
        rows = (await db.execute(select(MeetingDocumentRecord))).scalars().all()
        assert len(rows) == 1 and rows[0].document_id == doc_id and rows[0].included is True
        jobs = (await db.execute(select(Job).where(Job.type == "document_process"))).scalars().all()
        assert len(jobs) == 1

    items = (await client.get(f"/api/desktop/meetings/{mid}/documents", headers=h)).json()
    assert [(i["document_id"], i["source"], i["included"]) for i in items] == [(doc_id, "meeting", True)]


async def test_confirm_foreign_document_is_404(sm, client, monkeypatch):
    _enable_s3(monkeypatch)
    token_a = await _device(sm, await _user(sm, "a@t.local"))
    token_b = await _device(sm, await _user(sm, "b@t.local"))
    mid_a = (await _meeting(client, token_a))["meeting_id"]
    mid_b = (await _meeting(client, token_b))["meeting_id"]
    up = await client.post("/api/desktop/documents/upload-session", headers=_bearer(token_a),
                           json={"filename": "d.pdf", "size": 100, "meeting_id": mid_a})
    r = await client.post(f"/api/desktop/documents/{up.json()['document_id']}/confirm",
                          headers=_bearer(token_b), json={"meeting_id": mid_b})
    assert r.status_code == 404


async def test_list_includes_inherited_and_patch_hides(sm, client):
    cust_id, obj_id = await _customer_and_object(sm)
    user = await _user(sm)
    token = await _device(sm, user)
    h = _bearer(token)
    mid = (await _meeting(client, token, customer_id=cust_id, object_id=obj_id))["meeting_id"]
    async with sm() as db:
        def mk(name, **kw):
            return DocumentRecord(owner_user_id=user.id, created_by_user_id=user.id, original_name=name,
                                  file_ext=".pdf", status="ready", s3_key=f"k/{name}",
                                  doc_type="contract", doc_tags=["penalty", "price"],
                                  doc_meta={"number": "5"}, **kw)
        by_customer, by_object = mk("c.pdf", customer_id=cust_id), mk("o.pdf", object_id=obj_id)
        foreign = mk("f.pdf", customer_id=cust_id + 100)
        db.add_all([by_customer, by_object, foreign])
        await db.commit()
        ids = (by_customer.id, by_object.id, foreign.id)

    items = {i["document_id"]: i for i in (await client.get(f"/api/desktop/meetings/{mid}/documents", headers=h)).json()}
    assert set(items) == {ids[0], ids[1]}
    assert items[ids[0]]["source"] == "customer" and items[ids[1]]["source"] == "object"
    first = items[ids[0]]
    assert first["included"] is True and first["status"] == "ready"
    assert first["doc_type"] == "contract" and first["doc_type_label"] == "Договор"
    assert first["doc_tags"] == [{"key": "penalty", "label": "Неустойка / штрафы"},
                                 {"key": "price", "label": "Цена"}]
    assert first["doc_meta"] == {"number": "5"}

    r = await client.patch(f"/api/desktop/meetings/{mid}/documents/{ids[0]}", headers=h, json={"included": False})
    assert r.status_code == 200 and r.json()["included"] is False and r.json()["source"] == "customer"
    items = {i["document_id"]: i for i in (await client.get(f"/api/desktop/meetings/{mid}/documents", headers=h)).json()}
    assert items[ids[0]]["included"] is False and items[ids[1]]["included"] is True

    bad = await client.patch(f"/api/desktop/meetings/{mid}/documents/{ids[2]}", headers=h, json={"included": False})
    assert bad.status_code == 404


async def test_classification_vocab_route(sm, client):
    user = await _user(sm)
    r = await client.get("/api/documents/classification-vocab", headers=_jwt(user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"key": "contract", "label": "Договор"} in body["doc_types"]
    assert {"key": "penalty", "label": "Неустойка / штрафы"} in body["doc_tags"]


async def test_mobile_detail_lists_inherited_with_classification(sm, client):
    cust_id, _ = await _customer_and_object(sm)
    user = await _user(sm)
    mid = (await _meeting(client, await _device(sm, user), customer_id=cust_id))["meeting_id"]
    async with sm() as db:
        db.add(DocumentRecord(
            owner_user_id=user.id, created_by_user_id=user.id, original_name="c.pdf", file_ext=".pdf",
            status="ready", s3_key="k/c.pdf", doc_type="contract", doc_tags=["price"],
            doc_meta={"number": "5"}, customer_id=cust_id,
        ))
        await db.commit()

    r = await client.get(f"/api/mobile/meetings/{mid}", headers=_jwt(user))
    assert r.status_code == 200, r.text
    docs = r.json()["documents"]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["source"] == "customer" and doc["included"] is True and doc["id"] < 0
    assert doc["doc_type"] == "contract" and doc["doc_type_label"] == "Договор"
    assert doc["doc_tags"] == [{"key": "price", "label": "Цена"}]
    assert doc["doc_meta"] == {"number": "5"}
