# -*- coding: utf-8 -*-
"""Десктоп-приложение записи встреч: вход с токеном устройства и идемпотентный приём встречи.

Приложение повторяет любой запрос после обрыва сети, поэтому главное, что здесь проверяется, —
повтор не плодит дубли: ни встреч, ни сегментов, ни задач финализации.
"""

import uuid
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.service import create_access_token, hash_password
from app.config import get_settings
from app.database import Base, get_db
from app.models.desktop import DesktopDevice, DesktopMeetingLink
from app.models.file import FileRecord
from app.models.job import Job
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.meeting_conversation import MeetingSpeakerRole
from app.models.user import User
from app.ratelimit import limiter
from app.services import s3 as s3mod
from app.services.desktop_devices import enroll_device

PASSWORD = "s3cret-pass"
STARTED = "2026-10-21T09:00:00+00:00"


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
    from app.api import desktop as desktop_api
    from app.main import app

    async def _db():
        async with sm() as s:
            yield s

    events: list[tuple[str, dict]] = []

    async def _audit(event_type, actor_user_id=None, ip=None, **details):
        events.append((event_type, {"actor_user_id": actor_user_id, **details}))

    # audit пишет в отдельной сессии боевой БД — в тестах подменяем и заодно проверяем события.
    monkeypatch.setattr(desktop_api, "audit", _audit)
    limiter.reset()
    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.audit_events = events  # type: ignore[attr-defined]
            yield c
    finally:
        app.dependency_overrides.clear()
        limiter.reset()


async def _user(sm, email="eng@test.local", active=True, role="user") -> User:
    async with sm() as db:
        u = User(email=email, password_hash=hash_password(PASSWORD), role=role, is_active=active,
                 display_name="Инженер")
        db.add(u)
        await db.commit()
        return u


async def _device(sm, user: User) -> str:
    async with sm() as db:
        _, token = await enroll_device(db, user.id, "ПК", "windows", "0.1.0")
        await db.commit()
        return token


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _jwt(user: User) -> dict:
    return _bearer(create_access_token(user.id, user.role))


async def _meeting(client, token, mode="online", client_uuid=None, **extra) -> dict:
    body = {"client_uuid": client_uuid or str(uuid.uuid4()), "title": "Планерка",
            "started_at": STARTED, "capture_mode": mode, **extra}
    r = await client.post("/api/desktop/meetings", json=body, headers=_bearer(token))
    assert r.status_code == 200, r.text
    return r.json()


def _seg(cid="s1", text="Добрый день", start=0.0, end=1.5, channel="mic", **kw) -> dict:
    return {"client_segment_id": cid, "text": text, "start_time": start, "end_time": end,
            "channel": channel, **kw}


# ---------- вход ----------

async def test_login_ok_returns_token_stored_only_as_hash(sm, client):
    user = await _user(sm)
    r = await client.post("/api/desktop/login", json={
        "email": " ENG@test.local ", "password": PASSWORD, "device_name": "Рабочий ПК",
        "platform": "windows", "app_version": "0.1.0"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"] == {"id": user.id, "email": user.email, "display_name": "Инженер", "role": "user"}
    token = body["device_token"]
    async with sm() as db:
        dev = await db.get(DesktopDevice, body["device_id"])
        assert dev.name == "Рабочий ПК" and token not in dev.token_hash and len(dev.token_hash) == 64
    assert ("desktop_login_success", ) == (client.audit_events[-1][0], )
    assert "password" not in str(client.audit_events) and token not in str(client.audit_events)

    me = await client.get("/api/desktop/me", headers=_bearer(token))
    assert me.status_code == 200
    assert me.json()["user"]["id"] == user.id and me.json()["device"]["id"] == body["device_id"]
    assert "token" not in str(me.json())


async def test_login_wrong_password_and_unknown_user(sm, client):
    await _user(sm)
    r = await client.post("/api/desktop/login", json={
        "email": "eng@test.local", "password": "wrong", "device_name": "ПК"})
    assert r.status_code == 401
    r = await client.post("/api/desktop/login", json={
        "email": "nobody@test.local", "password": PASSWORD, "device_name": "ПК"})
    assert r.status_code == 401
    reasons = [d["reason"] for e, d in client.audit_events if e == "desktop_login_failed"]
    assert reasons == ["bad_password", "no_user"]
    # почта в аудите — только HMAC
    assert all("test.local" not in str(d) for _, d in client.audit_events)
    async with sm() as db:
        assert (await db.execute(select(func.count(DesktopDevice.id)))).scalar() == 0


async def test_login_inactive_user_rejected(sm, client):
    await _user(sm, active=False)
    r = await client.post("/api/desktop/login", json={
        "email": "eng@test.local", "password": PASSWORD, "device_name": "ПК"})
    assert r.status_code == 403
    assert client.audit_events[-1][0] == "desktop_login_failed"
    assert client.audit_events[-1][1]["reason"] == "inactive"


async def test_login_rate_limited(sm, client):
    codes = []
    for _ in range(6):
        r = await client.post("/api/desktop/login", json={
            "email": "x@test.local", "password": "bad", "device_name": "ПК"})
        codes.append(r.status_code)
    assert codes[:5] == [401] * 5 and codes[5] == 429


# ---------- токен устройства ----------

async def test_device_token_required(sm, client):
    r = await client.get("/api/desktop/me")
    assert r.status_code == 401
    r = await client.get("/api/desktop/me", headers=_bearer("wrong"))
    assert r.status_code == 401


async def test_logout_revokes_token(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    assert (await client.get("/api/desktop/me", headers=_bearer(token))).status_code == 200
    assert (await client.post("/api/desktop/logout", headers=_bearer(token))).status_code == 200
    assert (await client.get("/api/desktop/me", headers=_bearer(token))).status_code == 401
    assert client.audit_events[-1][0] == "desktop_device_revoked"


async def test_deactivated_user_token_rejected(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    async with sm() as db:
        (await db.get(User, user.id)).is_active = False
        await db.commit()
    assert (await client.get("/api/desktop/me", headers=_bearer(token))).status_code == 401


async def test_last_seen_updates_at_most_once_a_minute(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    async with sm() as db:
        dev = (await db.execute(select(DesktopDevice))).scalar_one()
        dev.last_seen_at = datetime(2020, 1, 1)
        await db.commit()
    await client.get("/api/desktop/me", headers=_bearer(token))
    async with sm() as db:
        first = (await db.execute(select(DesktopDevice))).scalar_one().last_seen_at
    assert first.year >= 2026
    await client.get("/api/desktop/me", headers=_bearer(token))
    async with sm() as db:
        assert (await db.execute(select(DesktopDevice))).scalar_one().last_seen_at == first


# ---------- устройства для сайта ----------

async def test_site_lists_and_revokes_own_devices(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    r = await client.get("/api/desktop/devices", headers=_jwt(user))
    assert r.status_code == 200 and len(r.json()) == 1
    assert "token" not in str(r.json())
    dev_id = r.json()[0]["id"]

    assert (await client.delete(f"/api/desktop/devices/{dev_id}", headers=_jwt(user))).status_code == 200
    assert (await client.get("/api/desktop/me", headers=_bearer(token))).status_code == 401
    assert (await client.get("/api/desktop/devices", headers=_jwt(user))).json() == []
    assert client.audit_events[-1][0] == "desktop_device_revoked"


async def test_site_cannot_revoke_foreign_device(sm, client):
    owner = await _user(sm, "owner@test.local")
    other = await _user(sm, "other@test.local")
    token = await _device(sm, owner)
    async with sm() as db:
        dev_id = (await db.execute(select(DesktopDevice.id))).scalar_one()
    r = await client.delete(f"/api/desktop/devices/{dev_id}", headers=_jwt(other))
    assert r.status_code == 404
    assert (await client.get("/api/desktop/me", headers=_bearer(token))).status_code == 200
    assert (await client.get("/api/desktop/devices", headers=_jwt(other))).json() == []


# ---------- встреча ----------

async def test_meeting_create_is_idempotent_and_updates(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    cu = str(uuid.uuid4())
    first = await _meeting(client, token, client_uuid=cu)
    assert first["created"] is True

    r = await client.post("/api/desktop/meetings", headers=_bearer(token), json={
        "client_uuid": cu, "title": "Планерка (итог)", "started_at": STARTED,
        "ended_at": "2026-10-21T10:00:00+00:00", "capture_mode": "online"})
    again = r.json()
    assert again == {"meeting_id": first["meeting_id"], "created": False}
    async with sm() as db:
        assert (await db.execute(select(func.count(MeetingSession.id)))).scalar() == 1
        assert (await db.execute(select(func.count(DesktopMeetingLink.id)))).scalar() == 1
        m = await db.get(MeetingSession, first["meeting_id"])
        assert m.title == "Планерка (итог)" and m.ended_at == datetime(2026, 10, 21, 10, 0)
        assert m.started_at == datetime(2026, 10, 21, 9, 0)
        assert m.user_id == user.id and m.created_by_user_id == user.id
        assert m.is_active is False and m.status == "active"


async def test_online_meeting_creates_side_roles(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token, "online"))["meeting_id"]
    async with sm() as db:
        roles = {r.speaker_label: r.side for r in (await db.execute(
            select(MeetingSpeakerRole).where(MeetingSpeakerRole.meeting_id == mid))).scalars()}
    assert roles == {"Мы": "self", "Оппонент": "opponent"}


async def test_in_person_meeting_has_no_roles(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token, "in_person"))["meeting_id"]
    async with sm() as db:
        assert (await db.execute(select(func.count(MeetingSpeakerRole.id)))).scalar() == 0
        assert mid


async def test_meeting_rejects_unknown_customer(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    r = await client.post("/api/desktop/meetings", headers=_bearer(token), json={
        "client_uuid": str(uuid.uuid4()), "title": "x", "started_at": STARTED,
        "capture_mode": "online", "customer_id": 9999})
    assert r.status_code == 422


# ---------- сегменты ----------

async def test_segments_upsert_without_duplicates(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    url = f"/api/desktop/meetings/{mid}/segments"
    batch = [
        _seg("a", "Добрый день, коллеги", 0, 2, "mic"),
        _seg("b", "Здравствуйте", 2, 3.5, "system", wall_clock="2026-10-21T09:00:03+00:00"),
        _seg("c", "Обсудим смету", 4, 6, "mixed", speaker_label="Иван"),
        _seg("d", "Без метки", 6, 7, "mixed"),
    ]
    r = await client.put(url, json={"segments": batch}, headers=_bearer(token))
    assert r.status_code == 200 and r.json() == {"created": 4, "updated": 0}

    batch[0]["text"] = "Добрый день, коллеги!"
    batch[0]["end_time"] = 2.4
    r = await client.put(url, json={"segments": batch}, headers=_bearer(token))
    assert r.json() == {"created": 0, "updated": 4}

    async with sm() as db:
        rows = {s.text: s for s in (await db.execute(
            select(TranscriptSegmentRecord).where(TranscriptSegmentRecord.session_id == mid))).scalars()}
    assert len(rows) == 4
    mic = rows["Добрый день, коллеги!"]
    assert (mic.speaker_id, mic.speaker_label, mic.origin) == ("desktop_mic", "Мы", "desktop")
    assert mic.end_time == 2.4 and mic.word_count == 3 and len(mic.segment_id) == 12
    assert (rows["Здравствуйте"].speaker_id, rows["Здравствуйте"].speaker_label) == ("desktop_system", "Оппонент")
    assert rows["Здравствуйте"].wall_clock == datetime(2026, 10, 21, 9, 0, 3)
    assert rows["Обсудим смету"].speaker_id == "desktop_mixed" and rows["Обсудим смету"].speaker_label == "Иван"
    assert rows["Без метки"].speaker_label == "Speaker_1"
    # wall_clock без значения = начало встречи + смещение
    assert rows["Без метки"].wall_clock == datetime(2026, 10, 21, 9, 0, 6)


async def test_segments_limit_and_validation(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    url = f"/api/desktop/meetings/{mid}/segments"
    too_many = [_seg(f"s{i}", f"реплика {i}") for i in range(501)]
    assert (await client.put(url, json={"segments": too_many}, headers=_bearer(token))).status_code == 422
    bad_channel = [_seg("x", channel="phone")]
    assert (await client.put(url, json={"segments": bad_channel}, headers=_bearer(token))).status_code == 422
    ok = [_seg(f"s{i}", f"реплика {i}") for i in range(500)]
    r = await client.put(url, json={"segments": ok}, headers=_bearer(token))
    assert r.status_code == 200 and r.json()["created"] == 500


async def test_foreign_meeting_is_404(sm, client):
    owner = await _user(sm, "owner@test.local")
    other = await _user(sm, "other@test.local")
    t_owner, t_other = await _device(sm, owner), await _device(sm, other)
    mid = (await _meeting(client, t_owner))["meeting_id"]
    h = _bearer(t_other)
    assert (await client.put(f"/api/desktop/meetings/{mid}/segments", json={"segments": [_seg()]},
                             headers=h)).status_code == 404
    assert (await client.patch(f"/api/desktop/meetings/{mid}", json={"title": "x"}, headers=h)).status_code == 404
    assert (await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)).status_code == 404
    assert (await client.post(f"/api/desktop/meetings/{mid}/audio-upload", headers=h, json={
        "filename": "a.opus", "size": 1, "channel": "mic"})).status_code in (404, 503)
    assert (await client.get("/api/desktop/meetings", headers=h)).json() == []
    assert (await client.put("/api/desktop/meetings/99999/segments", json={"segments": []},
                             headers=_bearer(t_owner))).status_code == 404


async def test_same_client_uuid_of_different_users_stay_separate(sm, client):
    a = await _user(sm, "a@test.local")
    b = await _user(sm, "b@test.local")
    ta, tb = await _device(sm, a), await _device(sm, b)
    cu = str(uuid.uuid4())
    ma = await _meeting(client, ta, client_uuid=cu)
    mb = await _meeting(client, tb, client_uuid=cu)
    assert ma["meeting_id"] != mb["meeting_id"] and mb["created"] is True


# ---------- заметки ----------

async def test_notes_are_formatted_sorted_and_replaced(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    url = f"/api/desktop/meetings/{mid}"
    r = await client.patch(url, headers=_bearer(token), json={"notes": [
        {"at_seconds": 125.7, "text": "Срок монтажа  45 дней"},
        {"at_seconds": 5, "text": "Спросить про\nаванс"},
        {"at_seconds": 3700, "text": "Итог"},
        {"at_seconds": 9, "text": "   "},
    ]})
    assert r.status_code == 200
    async with sm() as db:
        notes = (await db.get(MeetingSession, mid)).meeting_notes
    assert notes.split("\n") == ["[00:05] Спросить про аванс", "[02:05] Срок монтажа 45 дней", "[61:40] Итог"]

    # полная замена; без поля notes — не трогаем
    await client.patch(url, headers=_bearer(token), json={"title": "Новое имя"})
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.meeting_notes and m.title == "Новое имя"
    await client.patch(url, headers=_bearer(token), json={"notes": [{"at_seconds": 1, "text": "Одна"}]})
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).meeting_notes == "[00:01] Одна"
    await client.patch(url, headers=_bearer(token), json={"notes": []})
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).meeting_notes is None


# ---------- финализация ----------

async def test_finalize_enqueues_once_and_is_idempotent(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    h = _bearer(token)
    await client.put(f"/api/desktop/meetings/{mid}/segments", json={"segments": [_seg()]}, headers=h)

    r = await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued" and r.json()["meeting_id"] == mid
    r2 = await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)
    assert r2.status_code == 200 and r2.json()["status"] == "queued"

    async with sm() as db:
        jobs = (await db.execute(select(Job).where(Job.type == "meeting_finalize"))).scalars().all()
        assert len(jobs) == 1 and jobs[0].payload == {"meeting_id": mid}
        m = await db.get(MeetingSession, mid)
        assert m.status == "finalized" and m.ended_at is not None and m.is_active is False


async def test_segments_into_finalized_meeting_conflict(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    h = _bearer(token)
    await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)
    r = await client.put(f"/api/desktop/meetings/{mid}/segments", json={"segments": [_seg()]}, headers=h)
    assert r.status_code == 409


async def test_list_meetings_shows_status_and_protocol(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    cu = str(uuid.uuid4())
    mid = (await _meeting(client, token, client_uuid=cu))["meeting_id"]
    h = _bearer(token)
    item = (await client.get("/api/desktop/meetings", headers=h)).json()[0]
    assert item["meeting_id"] == mid and item["client_uuid"] == cu and item["title"] == "Планерка"
    assert item["finalization_status"] == "not_started" and item["protocol_ready"] is False

    await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        m.finalization_status = "completed"
        m.protocol_markdown = "# Протокол"
        await db.commit()
    item = (await client.get("/api/desktop/meetings", headers=h)).json()[0]
    assert item["finalization_status"] == "completed" and item["protocol_ready"] is True


# ---------- аудио ----------

async def test_audio_upload_without_s3_is_503(sm, client, monkeypatch):
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: False))
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    r = await client.post(f"/api/desktop/meetings/{mid}/audio-upload", headers=_bearer(token),
                          json={"filename": "mic.opus", "size": 1000, "channel": "mic"})
    assert r.status_code == 503
    async with sm() as db:
        assert (await db.execute(select(func.count(FileRecord.id)))).scalar() == 0


async def test_audio_upload_and_confirm_with_s3(sm, client, monkeypatch):
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: True))
    monkeypatch.setattr(s3mod, "presign_put", lambda key, ttl=None, **kw: f"https://s3.example/{key}?sig=x")
    heads = []

    async def _head(key):
        heads.append(key)
        return {"size": 4321, "content_type": "audio/ogg"}

    monkeypatch.setattr(s3mod, "head_object", _head)
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    h = _bearer(token)
    body = {"filename": "mic.opus", "size": 4321, "channel": "mic"}

    r = await client.post(f"/api/desktop/meetings/{mid}/audio-upload", headers=h, json=body)
    assert r.status_code == 200, r.text
    file_id = r.json()["file_id"]
    assert r.json()["upload_url"].startswith("https://s3.example/meridian/") and r.json()["status"] == "pending"
    # повтор — та же запись
    r2 = await client.post(f"/api/desktop/meetings/{mid}/audio-upload", headers=h, json=body)
    assert r2.json()["file_id"] == file_id and r2.json()["upload_url"]
    # другой канал — другая запись
    r3 = await client.post(f"/api/desktop/meetings/{mid}/audio-upload", headers=h,
                           json={**body, "channel": "system"})
    assert r3.json()["file_id"] != file_id

    c = await client.post(f"/api/desktop/meetings/{mid}/audio-confirm/{file_id}", headers=h)
    assert c.status_code == 200 and c.json() == {"file_id": file_id, "status": "active", "size": 4321}
    c2 = await client.post(f"/api/desktop/meetings/{mid}/audio-confirm/{file_id}", headers=h)
    assert c2.status_code == 200 and len(heads) == 1
    # после подтверждения повторный upload не просит грузить заново
    r4 = await client.post(f"/api/desktop/meetings/{mid}/audio-upload", headers=h, json=body)
    assert r4.json() == {"file_id": file_id, "upload_url": None, "status": "active"}

    async with sm() as db:
        rec = await db.get(FileRecord, file_id)
        assert rec.purpose == "meeting_audio" and rec.meeting_id == mid and rec.status == "active"
        assert rec.original_name == "mic_mic.opus"
        # обработка аудио не запускается
        assert (await db.execute(select(func.count(Job.id)))).scalar() == 0


async def test_audio_upload_rejects_bad_extension_and_size(sm, client, monkeypatch):
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: True))
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    h = _bearer(token)
    url = f"/api/desktop/meetings/{mid}/audio-upload"
    r = await client.post(url, headers=h, json={"filename": "x.exe", "size": 10, "channel": "mic"})
    assert r.status_code == 400
    r = await client.post(url, headers=h, json={"filename": "x.opus", "size": 600 * 1024 * 1024, "channel": "mic"})
    assert r.status_code == 400


async def test_audio_confirm_missing_object_is_400(sm, client, monkeypatch):
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: True))
    monkeypatch.setattr(s3mod, "presign_put", lambda key, ttl=None, **kw: "https://s3.example/x")

    async def _head(key):
        return None

    monkeypatch.setattr(s3mod, "head_object", _head)
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    h = _bearer(token)
    r = await client.post(f"/api/desktop/meetings/{mid}/audio-upload", headers=h,
                          json={"filename": "a.opus", "size": 5, "channel": "mixed"})
    c = await client.post(f"/api/desktop/meetings/{mid}/audio-confirm/{r.json()['file_id']}", headers=h)
    assert c.status_code == 400
