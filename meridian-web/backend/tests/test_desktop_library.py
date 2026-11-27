# -*- coding: utf-8 -*-
"""Библиотека десктоп-приложения: встречи сайта и проекты, только чтение по токену устройства."""

import uuid
from datetime import datetime

import httpx
import pytest_asyncio
import app.api.desktop_library as library_mod
from app.config import get_settings
from app.models.batch_job import BatchJob
from app.models.file import FileRecord
from app.models.protocol import MeetingActionItem, MeetingDecision, MeetingOpenQuestion, MeetingRisk
from app.services import s3 as s3mod
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.service import hash_password
from app.database import Base, get_db
from app.models.desktop import DesktopMeetingLink
from app.models.directory import Customer, ProjectObject
from app.models.meeting import MeetingDocumentRecord, MeetingSession, TranscriptSegmentRecord
from app.models.user import User
from app.ratelimit import limiter
from app.services.desktop_devices import enroll_device


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
            yield s

    limiter.reset()
    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        limiter.reset()


async def _user(sm, email="eng@test.local") -> User:
    async with sm() as db:
        u = User(email=email, password_hash=hash_password("pw-123456"), role="user",
                 is_active=True, display_name="Инженер", all_objects_access=True)
        db.add(u)
        await db.commit()
        return u


async def _device(sm, user: User) -> dict:
    async with sm() as db:
        _, token = await enroll_device(db, user.id, "ПК", "windows", "0.1.0")
        await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _site_meeting(sm, user: User, link_for: User | None = None, **kw) -> tuple[int, str | None]:
    """Встреча; link_for — завести связь приложения этого пользователя. -> (id, client_uuid)."""
    fields = dict(user_id=user.id, created_by_user_id=user.id, title="Планерка",
                  started_at=datetime(2026, 10, 21, 9, 0), is_active=False)
    fields.update(kw)
    cuid = None
    async with sm() as db:
        m = MeetingSession(**fields)
        db.add(m)
        await db.flush()
        if link_for is not None:
            cuid = str(uuid.uuid4())
            db.add(DesktopMeetingLink(user_id=link_for.id, client_uuid=cuid, meeting_id=m.id,
                                      capture_mode="online"))
        await db.commit()
        return m.id, cuid


async def test_library_requires_token(client):
    for path in ("/api/desktop/library", "/api/desktop/projects", "/api/desktop/meetings/1/view"):
        assert (await client.get(path)).status_code == 401


async def test_library_site_and_desktop_meetings(sm, client):
    me = await _user(sm)
    other = await _user(sm, "other@test.local")
    h = await _device(sm, me)
    site_id, _ = await _site_meeting(sm, other, title="С сайта",
                                     started_at=datetime(2026, 10, 20, 9, 0))
    own_id, own_uuid = await _site_meeting(sm, me, link_for=me, title="Своя",
                                           protocol_markdown="# Протокол",
                                           finalization_status="completed",
                                           micro_summary="кратко")
    alien_id, _ = await _site_meeting(sm, other, link_for=other, title="Чужая из приложения",
                                      started_at=datetime(2026, 10, 19, 9, 0))
    active_id, _ = await _site_meeting(sm, other, title="Идёт запись", is_active=True,
                                       started_at=datetime(2026, 10, 18, 9, 0))

    r = await client.get("/api/desktop/library", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()
    # started_at desc; незавершённая (is_active) тоже в списке
    assert [i["meeting_id"] for i in items] == [own_id, site_id, alien_id, active_id]
    own, site, alien, active = items
    assert [i["is_active"] for i in items] == [False, False, False, True]
    assert active["title"] == "Идёт запись"
    assert own["source"] == "desktop" and own["client_uuid"] == own_uuid
    assert own["protocol_ready"] is True and own["micro_summary"] == "кратко"
    assert own["finalization_status"] == "completed"
    assert site["source"] == "web" and site["client_uuid"] is None
    assert site["protocol_ready"] is False
    # встреча из чужого приложения: источник desktop, но uuid чужой — не отдаём
    assert alien["source"] == "desktop" and alien["client_uuid"] is None


async def test_library_filters_and_limit(sm, client):
    me = await _user(sm)
    h = await _device(sm, me)
    async with sm() as db:
        c1, c2 = Customer(name="Альфа"), Customer(name="Бета")
        db.add_all([c1, c2])
        await db.flush()
        o1 = ProjectObject(customer_id=c1.id, name="Дом 1")
        db.add(o1)
        await db.commit()
        c1_id, c2_id, o1_id = c1.id, c2.id, o1.id
    a, _ = await _site_meeting(sm, me, title="Бетон", customer_id=c1_id, object_id=o1_id)
    b, _ = await _site_meeting(sm, me, title="Кровля", meeting_topic="Гидроизоляция", customer_id=c2_id,
                               started_at=datetime(2026, 10, 20, 9, 0))

    def ids(r):
        return [i["meeting_id"] for i in r.json()]

    r = await client.get("/api/desktop/library", params={"q": "Бетон"}, headers=h)
    assert ids(r) == [a]
    r = await client.get("/api/desktop/library", params={"q": "Гидро"}, headers=h)
    assert ids(r) == [b]
    r = await client.get("/api/desktop/library", params={"customer_id": c2_id}, headers=h)
    assert ids(r) == [b] and r.json()[0]["customer_name"] == "Бета"
    r = await client.get("/api/desktop/library", params={"object_id": o1_id}, headers=h)
    assert ids(r) == [a] and r.json()[0]["object_name"] == "Дом 1"
    r = await client.get("/api/desktop/library", params={"limit": 1}, headers=h)
    assert ids(r) == [a]
    assert (await client.get("/api/desktop/library", params={"limit": 501}, headers=h)).status_code == 422


async def test_meeting_view(sm, client):
    me = await _user(sm)
    h = await _device(sm, me)
    mid, cuid = await _site_meeting(sm, me, link_for=me, protocol_markdown="# Протокол",
                                  negotiation_type="claim", meeting_notes="Аванс 30%",
                                  opponent_weaknesses="Горят сроки", app_notes="[00:01] Заметка")
    async with sm() as db:
        db.add_all([
            TranscriptSegmentRecord(session_id=mid, segment_id="s2", text="Второе", start_time=5.0,
                                    end_time=6.0, wall_clock=datetime(2026, 10, 21, 9, 0, 5),
                                    speaker_label="Оппонент", origin="final"),
            TranscriptSegmentRecord(session_id=mid, segment_id="s1", text="Первое", start_time=0.0,
                                    end_time=1.0, wall_clock=datetime(2026, 10, 21, 9, 0, 0),
                                    speaker_label="Мы", origin="final"),
            MeetingDocumentRecord(session_id=mid, filename="dogovor.pdf", doc_type="contract", page_count=3),
        ])
        await db.commit()

    r = await client.get(f"/api/desktop/meetings/{mid}/view", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meeting_id"] == mid and body["client_uuid"] == cuid and body["source"] == "desktop"
    assert body["protocol_markdown"] == "# Протокол"
    assert (body["negotiation_type"], body["key_terms"], body["opponent_weaknesses"], body["app_notes"]) == (
        "claim", "Аванс 30%", "Горят сроки", "[00:01] Заметка")
    assert [s["text"] for s in body["segments"]] == ["Первое", "Второе"]
    assert body["segments"][0]["speaker_label"] == "Мы"
    assert body["documents"][0]["filename"] == "dogovor.pdf" and body["documents"][0]["page_count"] == 3

    assert (await client.get("/api/desktop/meetings/9999/view", headers=h)).status_code == 404


async def test_projects_nested_active_objects(sm, client):
    me = await _user(sm)
    h = await _device(sm, me)
    async with sm() as db:
        beta, alfa, empty = Customer(name="Бета"), Customer(name="Альфа"), Customer(name="Гамма")
        db.add_all([beta, alfa, empty])
        await db.flush()
        db.add_all([
            ProjectObject(customer_id=alfa.id, name="Дом 2", address="ул. Ленина, 1"),
            ProjectObject(customer_id=alfa.id, name="Дом 1"),
            ProjectObject(customer_id=alfa.id, name="Закрытый", is_active=False),
            ProjectObject(customer_id=beta.id, name="Склад"),
        ])
        await db.commit()

    r = await client.get("/api/desktop/projects", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["name"] for c in body] == ["Альфа", "Бета", "Гамма"]
    assert [o["name"] for o in body[0]["objects"]] == ["Дом 1", "Дом 2"]
    assert body[0]["objects"][1]["address"] == "ул. Ленина, 1"
    assert [o["name"] for o in body[1]["objects"]] == ["Склад"]
    assert body[2]["objects"] == []


async def test_meeting_view_has_structured_protocol(sm, client):
    me = await _user(sm)
    h = await _device(sm, me)
    mid, _ = await _site_meeting(sm, me)
    empty_id, _ = await _site_meeting(sm, me)
    async with sm() as db:
        db.add_all([
            MeetingDecision(meeting_id=mid, text="Аванс 30%", status="accepted",
                            evidence_json='[{"timecode":"00:01","speaker":"Мы","quote":"ок"}]'),
            MeetingActionItem(meeting_id=mid, task="Выслать КП", owner_text="Иванов", due_text="до пятницы"),
            MeetingRisk(meeting_id=mid, text="Срыв сроков", severity="high"),
            MeetingOpenQuestion(meeting_id=mid, text="Кто платит за кран?"),
        ])
        await db.commit()

    body = (await client.get(f"/api/desktop/meetings/{mid}/view", headers=h)).json()
    assert body["decisions"][0]["text"] == "Аванс 30%" and body["decisions"][0]["status"] == "accepted"
    assert body["decisions"][0]["evidence"][0]["quote"] == "ок"
    assert body["action_items"][0]["task"] == "Выслать КП" and body["action_items"][0]["owner_text"] == "Иванов"
    assert body["risks"][0]["severity"] == "high"
    assert body["open_questions"][0]["text"] == "Кто платит за кран?"

    empty = (await client.get(f"/api/desktop/meetings/{empty_id}/view", headers=h)).json()
    assert (empty["decisions"], empty["action_items"], empty["risks"], empty["open_questions"]) == ([], [], [], [])


def _s3_on(monkeypatch, missing: set[str] | None = None):
    """S3 включён, presign подменён; missing — ключи, которых «нет в хранилище»."""
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: True))

    async def _head(key):
        return None if missing and key in missing else {"size": 10, "content_type": "audio/mpeg"}

    monkeypatch.setattr(s3mod, "head_object", _head)
    monkeypatch.setattr(s3mod, "presign_get", lambda key, ttl=None, download_name=None, public=True:
                        f"https://s3.example/get/{key}?sig=x")


async def _add_audio(sm, user, mid, *, batch=None, files=(), batch_kind=None):
    async with sm() as db:
        if batch:
            db.add(BatchJob(user_id=user.id, meeting_id=mid, original_filename="rec.mp3",
                            file_path=batch, kind=batch_kind))
        for channel, key, status in files:
            db.add(FileRecord(user_id=user.id, object_key=key, original_name=f"{channel}_rec.webm",
                              purpose="meeting_audio", status=status, meeting_id=mid))
        await db.commit()


async def test_meeting_audio_batch_has_priority(sm, client, monkeypatch):
    _s3_on(monkeypatch)
    me = await _user(sm)
    h = await _device(sm, me)
    mid, _ = await _site_meeting(sm, me)
    await _add_audio(sm, me, mid, batch="k/batch.mp3", files=[("mixed", "k/mixed.webm", "active")])
    r = await client.get(f"/api/desktop/meetings/{mid}/audio", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "batch" and body["url"].startswith("https://s3.example/get/k/batch.mp3")
    assert body["expires_in"] == get_settings().batch_audio_presign_ttl


async def test_meeting_audio_channel_order_and_skips(sm, client, monkeypatch):
    _s3_on(monkeypatch, missing={"k/mixed.webm"})
    me = await _user(sm)
    h = await _device(sm, me)
    mid, _ = await _site_meeting(sm, me)
    await _add_audio(sm, me, mid, files=[
        ("mic", "k/mic.webm", "active"), ("system", "k/system.webm", "active"),
        ("mixed", "k/mixed.webm", "active"),  # нет в S3 — берём следующий
    ])
    body = (await client.get(f"/api/desktop/meetings/{mid}/audio", headers=h)).json()
    assert body["source"] == "system" and body["url"].startswith("https://s3.example/get/k/system.webm")

    mid2, _ = await _site_meeting(sm, me)
    await _add_audio(sm, me, mid2, files=[("mic", "k/mic2.webm", "active"), ("mixed", "k/m2.webm", "pending")])
    assert (await client.get(f"/api/desktop/meetings/{mid2}/audio", headers=h)).json()["source"] == "mic"


async def test_meeting_audio_ignores_gap_fill_batch(sm, client, monkeypatch):
    _s3_on(monkeypatch)
    me = await _user(sm)
    h = await _device(sm, me)
    mid, _ = await _site_meeting(sm, me)
    await _add_audio(sm, me, mid, batch="k/gap.mp3", batch_kind="gap_fill")
    r = await client.get(f"/api/desktop/meetings/{mid}/audio", headers=h)
    assert r.status_code == 404 and r.json() == {"detail": "audio_not_found"}


async def test_meeting_audio_404_without_audio_or_s3(sm, client, monkeypatch):
    me = await _user(sm)
    h = await _device(sm, me)
    mid, _ = await _site_meeting(sm, me)
    _s3_on(monkeypatch)
    r = await client.get(f"/api/desktop/meetings/{mid}/audio", headers=h)
    assert r.status_code == 404 and r.json() == {"detail": "audio_not_found"}

    await _add_audio(sm, me, mid, batch="k/batch.mp3")
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: False))
    r = await client.get(f"/api/desktop/meetings/{mid}/audio", headers=h)
    assert r.status_code == 404 and r.json() == {"detail": "audio_not_found"}

    _s3_on(monkeypatch, missing={"k/batch.mp3"})
    r = await client.get(f"/api/desktop/meetings/{mid}/audio", headers=h)
    assert r.status_code == 404 and r.json() == {"detail": "audio_not_found"}


async def test_meeting_audio_unknown_or_forbidden_meeting(sm, client, monkeypatch):
    _s3_on(monkeypatch)
    me = await _user(sm)
    h = await _device(sm, me)
    assert (await client.get("/api/desktop/meetings/9999/audio", headers=h)).status_code == 404
    assert (await client.get("/api/desktop/meetings/1/audio")).status_code == 401

    mid, _ = await _site_meeting(sm, me)
    await _add_audio(sm, me, mid, batch="k/batch.mp3")

    async def _deny(db, user_id, meeting_id):
        return False

    monkeypatch.setattr(library_mod, "user_can_access_meeting", _deny)
    # тот же код, что у /view для встречи без доступа
    assert (await client.get(f"/api/desktop/meetings/{mid}/view", headers=h)).status_code == 403
    assert (await client.get(f"/api/desktop/meetings/{mid}/audio", headers=h)).status_code == 403
