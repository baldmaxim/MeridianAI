# -*- coding: utf-8 -*-
"""Десктоп: распознавание аудиофайла на сервере — upload-session, идемпотентный confirm, опрос."""

from sqlalchemy import func, select

from app.config import get_settings
from app.models.batch_job import BatchJob
from app.models.file import FileRecord
from app.models.job import Job
from app.services import s3 as s3mod

from .test_desktop_api import _bearer, _device, _user, client, sm  # noqa: F401

BASE = "/api/desktop/transcriptions"


def _enable_s3(monkeypatch, heads=None):
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: True))
    monkeypatch.setattr(s3mod, "presign_put", lambda key, ttl=None, **kw: "https://s3.example/put?sig=x")

    async def _head(key):
        if heads is not None:
            heads.append(key)
        return {"size": 1234, "content_type": "audio/mpeg"}

    monkeypatch.setattr(s3mod, "head_object", _head)


async def _session(client, token, filename="talk.mp3", size=1234):
    return await client.post(f"{BASE}/upload-session", headers=_bearer(token),
                             json={"filename": filename, "size": size})


async def _batch_jobs(sm):
    async with sm() as db:
        return (await db.execute(select(Job).where(Job.type == "batch_transcribe"))).scalars().all()


async def test_upload_session_ok(sm, client, monkeypatch):
    _enable_s3(monkeypatch)
    token = await _device(sm, await _user(sm))
    r = await _session(client, token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["upload_url"].startswith("https://s3.example/")
    assert "no-store" in r.headers["cache-control"]
    async with sm() as db:
        rec = await db.get(FileRecord, body["file_id"])
        assert (rec.purpose, rec.status, rec.original_name) == ("batch_audio", "pending", "talk.mp3")


async def test_upload_session_bad_extension_is_400(sm, client, monkeypatch):
    _enable_s3(monkeypatch)
    token = await _device(sm, await _user(sm))
    r = await _session(client, token, filename="doc.pdf")
    assert r.status_code == 400
    async with sm() as db:
        assert (await db.execute(select(func.count(FileRecord.id)))).scalar() == 0


async def test_upload_session_without_s3_is_503(sm, client, monkeypatch):
    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: False))
    token = await _device(sm, await _user(sm))
    r = await _session(client, token)
    assert r.status_code == 503


async def test_confirm_creates_job_and_is_idempotent(sm, client, monkeypatch):
    heads: list[str] = []
    _enable_s3(monkeypatch, heads)
    token = await _device(sm, await _user(sm))
    h = _bearer(token)
    file_id = (await _session(client, token)).json()["file_id"]

    first = await client.post(f"{BASE}/{file_id}/confirm", headers=h, json={"max_speakers": 3})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "uploaded" and first.json()["max_speakers"] == 3
    jobs = await _batch_jobs(sm)
    assert len(jobs) == 1 and jobs[0].payload == {"batch_job_id": first.json()["id"]}

    again = await client.post(f"{BASE}/{file_id}/confirm", headers=h)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert len(await _batch_jobs(sm)) == 1
    assert len(heads) == 1  # повтор S3 не трогает
    async with sm() as db:
        assert (await db.execute(select(func.count(BatchJob.id)))).scalar() == 1


async def test_confirm_unknown_or_foreign_file_is_404(sm, client, monkeypatch):
    _enable_s3(monkeypatch)
    token_a = await _device(sm, await _user(sm, "a@t.local"))
    token_b = await _device(sm, await _user(sm, "b@t.local"))
    file_id = (await _session(client, token_a)).json()["file_id"]
    assert (await client.post(f"{BASE}/{file_id}/confirm", headers=_bearer(token_b))).status_code == 404
    assert (await client.post(f"{BASE}/9999/confirm", headers=_bearer(token_a))).status_code == 404
    assert await _batch_jobs(sm) == []


async def test_get_returns_detail(sm, client, monkeypatch):
    _enable_s3(monkeypatch)
    token = await _device(sm, await _user(sm))
    h = _bearer(token)
    file_id = (await _session(client, token)).json()["file_id"]
    job_id = (await client.post(f"{BASE}/{file_id}/confirm", headers=h)).json()["id"]
    async with sm() as db:
        job = await db.get(BatchJob, job_id)
        job.status = "done"
        job.transcription_text = "Добрый день"
        await db.commit()

    r = await client.get(f"{BASE}/{job_id}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == job_id and body["status"] == "done"
    assert body["transcription_text"] == "Добрый день" and body["segments"] == []


async def test_get_foreign_job_is_404(sm, client, monkeypatch):
    _enable_s3(monkeypatch)
    token_a = await _device(sm, await _user(sm, "a@t.local"))
    token_b = await _device(sm, await _user(sm, "b@t.local"))
    file_id = (await _session(client, token_a)).json()["file_id"]
    job_id = (await client.post(f"{BASE}/{file_id}/confirm", headers=_bearer(token_a))).json()["id"]
    assert (await client.get(f"{BASE}/{job_id}", headers=_bearer(token_b))).status_code == 404


async def test_no_token_is_401(sm, client):
    assert (await client.post(f"{BASE}/upload-session", json={"filename": "a.mp3", "size": 1})).status_code == 401
    assert (await client.post(f"{BASE}/1/confirm")).status_code == 401
    assert (await client.get(f"{BASE}/1")).status_code == 401
