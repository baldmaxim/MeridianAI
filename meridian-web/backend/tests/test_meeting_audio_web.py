# -*- coding: utf-8 -*-
"""GET /api/meetings/{id}/audio: части записи встречи для плеера на сайте."""

from datetime import datetime

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.api.history as history_mod
from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.database import Base, get_db
from app.models.batch_job import BatchJob
from app.models.file import FileRecord
from app.models.meeting import MeetingSession
from app.models.user import User
from app.services import s3 as s3mod


@pytest_asyncio.fixture
async def env():
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        user = User(email="eng@t.local", password_hash="x", role="user", is_active=True)
        s.add(user)
        await s.commit()

    async def _db():
        async with sm() as s:
            yield s

    async def _cur():
        return user

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _cur
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield sm, user, c
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def _s3_on(monkeypatch, missing: set[str] | None = None):
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: True))

    async def _head(key):
        return None if missing and key in missing else {"size": 10, "content_type": "audio/mpeg"}

    monkeypatch.setattr(s3mod, "head_object", _head)
    monkeypatch.setattr(s3mod, "presign_get", lambda key, ttl=None, download_name=None, public=True:
                        f"https://s3.example/get/{key}?sig=x")


async def _meeting(sm, user) -> int:
    async with sm() as db:
        m = MeetingSession(user_id=user.id, created_by_user_id=user.id, title="Планерка",
                           started_at=datetime(2026, 10, 21, 9, 0), is_active=False)
        db.add(m)
        await db.commit()
        return m.id


async def _add(sm, user, mid, *, batch=None, names=()):
    """names — (original_name, object_key); записи создаются по порядку (растущий id)."""
    async with sm() as db:
        if batch:
            db.add(BatchJob(user_id=user.id, meeting_id=mid, original_filename="rec.mp3", file_path=batch))
        for name, key in names:
            db.add(FileRecord(user_id=user.id, object_key=key, original_name=name,
                              purpose="meeting_audio", status="active", meeting_id=mid))
            await db.flush()
        await db.commit()


async def test_audio_404_without_audio(env, monkeypatch):
    sm, user, c = env
    _s3_on(monkeypatch)
    mid = await _meeting(sm, user)
    r = await c.get(f"/api/meetings/{mid}/audio")
    assert r.status_code == 404 and r.json() == {"detail": "audio_not_found"}


async def test_audio_batch_has_priority(env, monkeypatch):
    sm, user, c = env
    _s3_on(monkeypatch)
    mid = await _meeting(sm, user)
    await _add(sm, user, mid, batch="k/batch.mp3",
               names=[("mixed_rec.webm", "k/mixed.webm"), ("meeting_1.ogg", "k/live.ogg")])
    r = await c.get(f"/api/meetings/{mid}/audio")
    assert r.status_code == 200, r.text
    parts = r.json()["parts"]
    assert len(parts) == 1
    assert parts[0]["source"] == "batch" and parts[0]["url"].startswith("https://s3.example/get/k/batch.mp3")
    assert parts[0]["expires_in"] == get_settings().batch_audio_presign_ttl


async def test_audio_desktop_channel_priority(env, monkeypatch):
    sm, user, c = env
    _s3_on(monkeypatch)
    mid = await _meeting(sm, user)
    await _add(sm, user, mid, names=[("mic_rec.webm", "k/mic.webm"), ("system_rec.webm", "k/system.webm"),
                                      ("meeting_1.ogg", "k/live.ogg")])
    parts = (await c.get(f"/api/meetings/{mid}/audio")).json()["parts"]
    assert [p["source"] for p in parts] == ["system"]


async def test_audio_several_live_parts_in_order(env, monkeypatch):
    sm, user, c = env
    _s3_on(monkeypatch, missing={"k/live2.ogg"})
    mid = await _meeting(sm, user)
    await _add(sm, user, mid, names=[("meeting_5.ogg", "k/live1.ogg"), ("meeting_5.ogg", "k/live2.ogg"),
                                      ("meeting_5.ogg", "k/live3.ogg")])
    parts = (await c.get(f"/api/meetings/{mid}/audio")).json()["parts"]
    # часть без объекта в хранилище пропущена, нумерация — по найденным
    assert [(p["source"], p["name"]) for p in parts] == [("live", "Часть 1"), ("live", "Часть 2")]
    assert parts[0]["url"].startswith("https://s3.example/get/k/live1.ogg")
    assert parts[1]["url"].startswith("https://s3.example/get/k/live3.ogg")

    mid2 = await _meeting(sm, user)
    await _add(sm, user, mid2, names=[("meeting_6.ogg", "k/a.ogg"), ("meeting_6.ogg", "k/b.ogg")])
    parts = (await c.get(f"/api/meetings/{mid2}/audio")).json()["parts"]
    assert [p["url"].split("/get/")[1].split("?")[0] for p in parts] == ["k/a.ogg", "k/b.ogg"]


async def test_audio_404_when_s3_off(env, monkeypatch):
    sm, user, c = env
    _s3_on(monkeypatch)
    mid = await _meeting(sm, user)
    await _add(sm, user, mid, batch="k/batch.mp3", names=[("meeting_1.ogg", "k/live.ogg")])
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: False))
    r = await c.get(f"/api/meetings/{mid}/audio")
    assert r.status_code == 404 and r.json() == {"detail": "audio_not_found"}


async def test_audio_unknown_or_forbidden_meeting(env, monkeypatch):
    sm, user, c = env
    _s3_on(monkeypatch)
    assert (await c.get("/api/meetings/9999/audio")).json() == {"detail": "Встреча не найдена"}
    mid = await _meeting(sm, user)
    await _add(sm, user, mid, batch="k/batch.mp3")

    async def _deny(db, user_id, meeting_id):
        return False

    monkeypatch.setattr(history_mod, "user_can_access_meeting", _deny)
    r = await c.get(f"/api/meetings/{mid}/audio")
    assert r.status_code == 403 and r.json() == {"detail": "Нет доступа к встрече"}
