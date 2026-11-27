# -*- coding: utf-8 -*-
"""Десктоп: подача КП (upsert/PATCH/просмотр/документы/список подач), буст чанков подачи, reopen, library."""

import uuid
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select

from app.config import get_settings
from app.models.directory import Customer, ProjectObject
from app.models.document import DocumentChunk, DocumentRecord
from app.models.file import FileRecord
from app.models.job import Job
from app.models.meeting import MeetingSession
from app.services.document_context import (
    OFFER_SUBMISSION_BOOST,
    _rank_rows,
    get_relevant_chunks_for_meeting,
)

from .test_desktop_api import STARTED, _bearer, _device, _meeting, _seg, _user, client, sm  # noqa: F401
from .test_desktop_library import _site_meeting

SUB_1 = "001 15.06.2026 Первичная"
SUB_2 = "002 29.06.2026 Скидка"


async def _object_with_offers(sm, user):
    """Объект: общий документ (NULL), две подачи (2 + 1 документа) и «вне папок» (""). -> object_id."""
    async with sm() as db:
        cust = Customer(name="Заказчик")
        db.add(cust)
        await db.flush()
        obj = ProjectObject(customer_id=cust.id, name="Объект")
        db.add(obj)
        await db.flush()
        for name, sub, date in (
            ("ocr.txt", None, None), ("a1.txt", SUB_1, "2026-06-15"), ("a2.txt", SUB_1, "2026-06-15"),
            ("b.txt", SUB_2, "2026-06-29"), ("free.txt", "", None),
        ):
            meta = {"import_source": {"kind": "offer", "submission": sub, "date": date}} if date else None
            db.add(DocumentRecord(
                owner_user_id=user.id, created_by_user_id=user.id, original_name=name, file_ext=".txt",
                status="ready", s3_key=f"k/{name}", object_id=obj.id, customer_id=cust.id,
                offer_submission=sub, doc_meta=meta,
            ))
        await db.commit()
        return obj.id, cust.id


# ---------- список подач ----------

async def test_object_offer_submissions_endpoint(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    object_id, _ = await _object_with_offers(sm, user)

    r = await client.get(f"/api/desktop/objects/{object_id}/offer-submissions", headers=_bearer(token))
    assert r.status_code == 200, r.text
    # без "" и NULL; новые сверху, как на сайте
    assert r.json() == [
        {"value": SUB_2, "label": SUB_2, "document_count": 1},
        {"value": SUB_1, "label": SUB_1, "document_count": 2},
    ]
    assert (await client.get("/api/desktop/objects/9999/offer-submissions",
                             headers=_bearer(token))).status_code == 404
    assert (await client.get(f"/api/desktop/objects/{object_id}/offer-submissions")).status_code == 401


# ---------- upsert / PATCH подачи ----------

async def test_upsert_offer_submission_validated_and_saved(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    object_id, customer_id = await _object_with_offers(sm, user)
    h = _bearer(token)
    base = {"client_uuid": str(uuid.uuid4()), "title": "Встреча", "started_at": STARTED,
            "capture_mode": "online", "customer_id": customer_id, "object_id": object_id}

    bad = await client.post("/api/desktop/meetings", json={**base, "offer_submission": "нет такой"}, headers=h)
    assert bad.status_code == 422
    async with sm() as db:  # неудачный upsert встречу не создал
        assert (await db.execute(select(MeetingSession))).first() is None

    ok = await client.post("/api/desktop/meetings", json={**base, "offer_submission": SUB_1}, headers=h)
    assert ok.status_code == 200, ok.text
    mid = ok.json()["meeting_id"]
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).offer_submission == SUB_1

    # повтор без поля — подачу не трогает; с другой — меняет; с несуществующей — 422
    await client.post("/api/desktop/meetings", json=base, headers=h)
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).offer_submission == SUB_1
    again = await client.post("/api/desktop/meetings", json={**base, "offer_submission": SUB_2}, headers=h)
    assert again.status_code == 200
    bad2 = await client.post("/api/desktop/meetings", json={**base, "offer_submission": "нет такой"}, headers=h)
    assert bad2.status_code == 422
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).offer_submission == SUB_2


async def test_upsert_offer_submission_without_object_is_422(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    r = await client.post("/api/desktop/meetings", headers=_bearer(token), json={
        "client_uuid": str(uuid.uuid4()), "title": "x", "started_at": STARTED,
        "capture_mode": "online", "offer_submission": SUB_1})
    assert r.status_code == 422


async def test_patch_offer_submission(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    object_id, customer_id = await _object_with_offers(sm, user)
    h = _bearer(token)
    mid = (await _meeting(client, token, customer_id=customer_id, object_id=object_id))["meeting_id"]
    url = f"/api/desktop/meetings/{mid}"

    async def current():
        async with sm() as db:
            return (await db.get(MeetingSession, mid)).offer_submission

    assert (await client.patch(url, json={"offer_submission": "нет такой"}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"offer_submission": SUB_2}, headers=h)).status_code == 200
    assert await current() == SUB_2
    # поле не передано — не меняем
    assert (await client.patch(url, json={"title": "Новое"}, headers=h)).status_code == 200
    assert await current() == SUB_2
    # явный null — сброс (все документы объекта)
    assert (await client.patch(url, json={"offer_submission": None}, headers=h)).status_code == 200
    assert await current() is None


# ---------- просмотр и документы встречи ----------

async def test_view_and_documents_expose_offer_submission(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    object_id, customer_id = await _object_with_offers(sm, user)
    h = _bearer(token)
    mid = (await _meeting(client, token, customer_id=customer_id, object_id=object_id))["meeting_id"]

    view = (await client.get(f"/api/desktop/meetings/{mid}/view", headers=h)).json()
    assert view["offer_submission"] is None and view["offer_submission_label"] is None

    await client.patch(f"/api/desktop/meetings/{mid}", json={"offer_submission": SUB_2}, headers=h)
    view = (await client.get(f"/api/desktop/meetings/{mid}/view", headers=h)).json()
    assert view["offer_submission"] == SUB_2 and view["offer_submission_label"] == SUB_2

    docs = (await client.get(f"/api/desktop/meetings/{mid}/documents", headers=h)).json()
    by_name = {d["original_name"]: d for d in docs}
    # выбрана подача 2: общий документ + её документ; остальные подачи не наследуются
    assert set(by_name) == {"ocr.txt", "b.txt"}
    assert by_name["b.txt"]["offer_submission"] == SUB_2
    assert by_name["ocr.txt"]["offer_submission"] is None

    # «вне папок подач» отдаётся человекочитаемой подписью
    async with sm() as db:
        (await db.get(MeetingSession, mid)).offer_submission = ""
        await db.commit()
    view = (await client.get(f"/api/desktop/meetings/{mid}/view", headers=h)).json()
    assert view["offer_submission"] == "" and view["offer_submission_label"] == "Вне папок подач"


# ---------- буст чанков подачи ----------

def _row(text, submission, idx=0):
    return SimpleNamespace(text=text, offer_submission=submission, priority=100, chunk_index=idx)


def test_rank_rows_boost_only_for_offer_chunks_with_bm25():
    rows = [_row("неустойка за просрочку", None), _row("неустойка за просрочку", SUB_1, 1),
            _row("совсем другое содержание", SUB_1, 2)]
    plain = {r.chunk_index: s for s, r in _rank_rows(rows, "неустойка просрочка")}
    # подача не задана: любая непустая подача получает буст
    boosted = {r.chunk_index: s for s, r in _rank_rows(rows, "неустойка просрочка", None)}
    assert set(boosted) == {0, 1}  # нерелевантный (bm25 = 0) не поднимается и не попадает в выдачу
    assert boosted[1] > boosted[0]
    base = boosted[0] - 100 / 100000.0
    assert abs((boosted[1] - 100 / 100000.0) - base * OFFER_SUBMISSION_BOOST) < 1e-9
    assert plain.keys() == boosted.keys()

    # подача встречи задана — буст только её чанкам
    rows = [_row("неустойка за просрочку", SUB_1), _row("неустойка за просрочку", SUB_2, 1)]
    scores = {r.chunk_index: s for s, r in _rank_rows(rows, "неустойка просрочка", SUB_2)}
    assert scores[1] > scores[0]

    # «вне папок» ("") и NULL не бустятся
    rows = [_row("неустойка за просрочку", ""), _row("неустойка за просрочку", None, 1)]
    scores = {r.chunk_index: s for s, r in _rank_rows(rows, "неустойка просрочка")}
    assert scores[0] == scores[1]


async def test_relevant_chunks_prefer_offer_documents(db):
    from app.models.user import User

    user = User(email="boost@t.local", password_hash="x", role="user", is_active=True, all_objects_access=True)
    cust = Customer(name="A")
    db.add_all([user, cust])
    await db.flush()
    obj = ProjectObject(customer_id=cust.id, name="О")
    db.add(obj)
    await db.flush()
    docs = {}
    for name, sub in (("common.txt", None), ("offer.txt", SUB_1)):
        d = DocumentRecord(owner_user_id=user.id, created_by_user_id=user.id, original_name=name,
                           file_ext=".txt", status="ready", s3_key=f"k/{name}", object_id=obj.id,
                           customer_id=cust.id, offer_submission=sub)
        db.add(d)
        await db.flush()
        db.add(DocumentChunk(document_id=d.id, chunk_index=0, text="неустойка за просрочку платежа"))
        docs[name] = d
    m = MeetingSession(user_id=user.id, created_by_user_id=user.id, is_active=True, status="active",
                       customer_id=cust.id, object_id=obj.id)
    db.add(m)
    await db.flush()

    hits = await get_relevant_chunks_for_meeting(db, m.id, "неустойка просрочка", limit=2)
    assert [h["document_name"] for h in hits] == ["offer.txt", "common.txt"]
    assert hits[0]["score"] > hits[1]["score"]


# ---------- reopen ----------

async def test_reopen_409_while_processing_and_200_after(sm, client, monkeypatch):
    user = await _user(sm)
    token = await _device(sm, user)
    h = _bearer(token)
    mid = (await _meeting(client, token))["meeting_id"]
    await client.put(f"/api/desktop/meetings/{mid}/segments", json={"segments": [_seg()]}, headers=h)
    await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)  # queued
    url = f"/api/desktop/meetings/{mid}/reopen"

    r = await client.post(url, headers=h)
    assert r.status_code == 409
    assert r.json()["detail"] == "Встреча ещё обрабатывается на сервере, попробуйте через минуту"

    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        m.finalization_status = "running"
        await db.commit()
    assert (await client.post(url, headers=h)).status_code == 409

    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        m.finalization_status = "completed"
        m.protocol_markdown = "# Старый протокол"
        m.refine_status = "running"
        await db.commit()
    assert (await client.post(url, headers=h)).status_code == 409

    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        m.refine_status = "done"
        await db.commit()
    r = await client.post(url, headers=h)
    assert r.status_code == 200 and r.json() == {"ok": True}
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.is_active is True and m.ended_at is None and m.status == "active"
        assert m.finalization_status == "not_started" and m.refine_status is None
        assert m.protocol_markdown == "# Старый протокол"  # протокол не стираем

    assert (await client.post(f"/api/desktop/meetings/9999/reopen", headers=h)).status_code == 404
    assert (await client.post(url)).status_code == 401


async def test_reopen_then_segments_and_refinalize_with_refine(sm, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "desktop_refine_enabled", True)
    user = await _user(sm)
    token = await _device(sm, user)
    h = _bearer(token)
    mid = (await _meeting(client, token))["meeting_id"]
    async with sm() as db:  # аудио, загруженное в первый раз
        db.add(FileRecord(user_id=user.id, object_key="k/mic_a.wav", original_name="mic_a.wav", size=10,
                          purpose="meeting_audio", status="active", meeting_id=mid))
        await db.commit()

    await client.put(f"/api/desktop/meetings/{mid}/segments", json={"segments": [_seg("s1")]}, headers=h)
    await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)
    async with sm() as db:  # сервер всё обработал
        m = await db.get(MeetingSession, mid)
        assert m.refine_status == "pending"
        m.refine_status = "done"
        m.finalization_status = "completed"
        await db.commit()
    assert (await client.post(f"/api/desktop/meetings/{mid}/reopen", headers=h)).status_code == 200

    # дозапись принимается (нет «уже финализирована»)
    r = await client.put(f"/api/desktop/meetings/{mid}/segments",
                         json={"segments": [_seg("s2", text="Продолжаем", start=5, end=6)]}, headers=h)
    assert r.status_code == 200 and r.json()["created"] == 1

    # повторный finalize снова ставит уточнение (аудио есть) — а оно само запросит протокол
    r = await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)
    assert r.status_code == 200
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.status == "finalized" and m.is_active is False and m.refine_status == "pending"
        types = [j.type for j in (await db.execute(select(Job).order_by(Job.id))).scalars().all()]
        assert types.count("meeting_refine") == 2

    # без аудио — сразу протокол
    mid2 = (await _meeting(client, token))["meeting_id"]
    await client.post(f"/api/desktop/meetings/{mid2}/finalize", headers=h)
    async with sm() as db:
        m = await db.get(MeetingSession, mid2)
        m.finalization_status = "completed"
        await db.commit()
    await client.post(f"/api/desktop/meetings/{mid2}/reopen", headers=h)
    r = await client.post(f"/api/desktop/meetings/{mid2}/finalize", headers=h)
    assert r.json()["status"] == "queued"


# ---------- library: refine pending/running не прячет встречу ----------

async def test_library_shows_meeting_while_refine_pending_or_running(sm, client):
    user = await _user(sm)
    other = await _user(sm, "other@test.local")
    h = _bearer(await _device(sm, other))
    ids = {}
    for status in ("pending", "running", "done", "failed"):
        mid, _ = await _site_meeting(sm, user, link_for=user, title=f"R-{status}",
                                     refine_status=status, status="finalized",
                                     finalization_status="not_started",
                                     started_at=datetime(2026, 10, 21, 9, 0))
        ids[status] = mid

    items = (await client.get("/api/desktop/library", headers=h)).json()
    got = {i["meeting_id"]: i["refine_status"] for i in items}
    assert got == {mid: status for status, mid in ids.items()}  # видны другим устройствам/пользователям

    # переоткрытая (is_active=True) тоже видна, с пометкой is_active
    async with sm() as db:
        (await db.get(MeetingSession, ids["done"])).is_active = True
        await db.commit()
    items = (await client.get("/api/desktop/library", headers=h)).json()
    flags = {i["meeting_id"]: i["is_active"] for i in items}
    assert flags[ids["done"]] is True
    assert [flags[ids[s]] for s in ("pending", "running", "failed")] == [False, False, False]
