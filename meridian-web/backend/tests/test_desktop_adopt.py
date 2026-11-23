# -*- coding: utf-8 -*-
"""Десктоп: «Продолжить в приложении» для встречи без локальной копии (POST /meetings/{id}/adopt)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.config import get_settings
from app.models.desktop import DesktopMeetingLink
from app.models.directory import Customer, ProjectObject
from app.models.file import FileRecord
from app.models.job import Job
from app.models.meeting import MeetingSession

from .test_desktop_api import STARTED, _bearer, _device, _meeting, _seg, _user, client, sm  # noqa: F401
from .test_desktop_library import _site_meeting


def _url(mid: int) -> str:
    return f"/api/desktop/meetings/{mid}/adopt"


def _body(cuid: str | None = None, mode: str = "online") -> dict:
    return {"client_uuid": cuid or str(uuid.uuid4()), "capture_mode": mode}


async def _links(sm, mid: int) -> list[DesktopMeetingLink]:
    async with sm() as db:
        return list((await db.execute(
            select(DesktopMeetingLink).where(DesktopMeetingLink.meeting_id == mid)
        )).scalars().all())


async def _audio(sm, user, mid: int, name: str, status: str = "active") -> None:
    async with sm() as db:
        db.add(FileRecord(user_id=user.id, object_key=f"k/{mid}/{name}", original_name=name, size=10,
                          purpose="meeting_audio", status=status, meeting_id=mid))
        await db.commit()


async def test_adopt_creates_link_and_reopens(sm, client):
    user = await _user(sm)
    h = _bearer(await _device(sm, user))
    async with sm() as db:
        cust = Customer(name="Заказчик")
        db.add(cust)
        await db.flush()
        obj = ProjectObject(customer_id=cust.id, name="Объект")
        db.add(obj)
        await db.flush()
        cust_id, obj_id = cust.id, obj.id
        await db.commit()
    mid, _ = await _site_meeting(
        sm, user, title="С сайта", status="finalized", finalization_status="completed",
        refine_status="done", ended_at=datetime(2026, 10, 21, 10, 0), customer_id=cust_id,
        object_id=obj_id, diarization_max_speakers=3, protocol_markdown="# Протокол",
        negotiation_type="price", meeting_notes="срок 3 месяца", opponent_weaknesses="затягивает оплату",
    )
    cuid = str(uuid.uuid4())

    r = await client.post(_url(mid), json=_body(cuid, "in_person"), headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["client_uuid"] == cuid and out["server_meeting_id"] == mid
    assert out["title"] == "С сайта" and out["capture_mode"] == "in_person"
    assert out["customer_id"] == cust_id and out["object_id"] == obj_id
    assert out["customer_name"] == "Заказчик" and out["object_name"] == "Объект"
    assert out["max_speakers"] == 3 and out["next_audio_revision"] == 1
    assert out["started_at"].startswith("2026-10-21T09:00")
    assert out["negotiation_type"] == "price" and out["key_terms"] == "срок 3 месяца"
    assert out["opponent_weaknesses"] == "затягивает оплату"

    links = await _links(sm, mid)
    assert len(links) == 1 and links[0].client_uuid == cuid and links[0].user_id == user.id
    assert links[0].adopted_at is not None and links[0].capture_mode == "in_person"
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.is_active is True and m.ended_at is None and m.status == "active"
        assert m.finalization_status == "not_started" and m.refine_status is None
        assert m.protocol_markdown == "# Протокол"

    # Встреча теперь «своя»: сегменты принимаются по обычным ручкам.
    r = await client.put(f"/api/desktop/meetings/{mid}/segments", json={"segments": [_seg()]}, headers=h)
    assert r.status_code == 200 and r.json()["created"] == 1

    assert (await client.post(_url(9999), json=_body(), headers=h)).status_code == 404
    assert (await client.post(_url(mid), json=_body())).status_code == 401


async def test_adopt_blank_title_and_empty_context_come_as_null(sm, client):
    user = await _user(sm)
    h = _bearer(await _device(sm, user))
    mid, _ = await _site_meeting(sm, user, title="  ")
    r = await client.post(_url(mid), json=_body(), headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["title"] is None
    assert out["negotiation_type"] is None and out["key_terms"] is None
    assert out["opponent_weaknesses"] is None


async def test_adopt_twice_returns_existing_client_uuid(sm, client):
    user = await _user(sm)
    h = _bearer(await _device(sm, user))
    mid, _ = await _site_meeting(sm, user)
    first = _body()
    assert (await client.post(_url(mid), json=first, headers=h)).status_code == 200

    r = await client.post(_url(mid), json=_body(), headers=h)  # другой uuid с другого ПК
    assert r.status_code == 200
    assert r.json()["client_uuid"] == first["client_uuid"]
    assert len(await _links(sm, mid)) == 1


async def test_adopt_meeting_already_linked_keeps_min_uuid_and_marks_adopted(sm, client):
    user = await _user(sm)
    h = _bearer(await _device(sm, user))
    mid, cuid = await _site_meeting(sm, user, link_for=user)
    assert (await _links(sm, mid))[0].adopted_at is None

    r = await client.post(_url(mid), json=_body(), headers=h)
    assert r.status_code == 200 and r.json()["client_uuid"] == cuid
    links = await _links(sm, mid)
    assert len(links) == 1 and links[0].adopted_at is not None


async def test_adopt_client_uuid_taken_by_other_meeting_409(sm, client):
    user = await _user(sm)
    h = _bearer(await _device(sm, user))
    taken = (await _meeting(client, await _device(sm, user)))["meeting_id"]
    taken_uuid = (await _links(sm, taken))[0].client_uuid
    mid, _ = await _site_meeting(sm, user)

    r = await client.post(_url(mid), json=_body(taken_uuid), headers=h)
    assert r.status_code == 409
    assert await _links(sm, mid) == []
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).is_active is False


async def test_adopt_409_while_server_processes(sm, client):
    user = await _user(sm)
    h = _bearer(await _device(sm, user))
    mid, _ = await _site_meeting(sm, user, finalization_status="running")
    assert (await client.post(_url(mid), json=_body(), headers=h)).status_code == 409
    assert await _links(sm, mid) == []
    mid2, _ = await _site_meeting(sm, user, refine_status="running")
    assert (await client.post(_url(mid2), json=_body(), headers=h)).status_code == 409
    assert await _links(sm, mid2) == []


async def test_adopt_next_audio_revision(sm, client):
    user = await _user(sm)
    h = _bearer(await _device(sm, user))

    mid, _ = await _site_meeting(sm, user)  # файлов нет
    assert (await client.post(_url(mid), json=_body(), headers=h)).json()["next_audio_revision"] == 1

    mid1, _ = await _site_meeting(sm, user)
    await _audio(sm, user, mid1, "mic_mic.wav")
    assert (await client.post(_url(mid1), json=_body(), headers=h)).json()["next_audio_revision"] == 2

    mid2, _ = await _site_meeting(sm, user)
    await _audio(sm, user, mid2, "mic_mic.wav")
    await _audio(sm, user, mid2, "mic_mic_r2.wav")
    await _audio(sm, user, mid2, "system_system_r7.wav", status="pending")  # не активный — не считается
    await _audio(sm, user, mid2, "заметки.wav")  # чужое имя — не считается
    assert (await client.post(_url(mid2), json=_body(), headers=h)).json()["next_audio_revision"] == 3


async def test_finalize_adopted_skips_refine(sm, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "desktop_refine_enabled", True)
    user = await _user(sm)
    h = _bearer(await _device(sm, user))
    mid, _ = await _site_meeting(sm, user)
    await _audio(sm, user, mid, "mic_mic.wav")
    assert (await client.post(_url(mid), json=_body(), headers=h)).status_code == 200
    await _audio(sm, user, mid, "mic_mic_r2.wav")

    r = await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)
    assert r.status_code == 200, r.text
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.refine_status == "skipped" and m.status == "finalized"
        types = [j.type for j in (await db.execute(select(Job))).scalars().all()]
        assert "meeting_refine" not in types


async def test_finalize_not_adopted_still_refines(sm, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "desktop_refine_enabled", True)
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    await _audio(sm, user, mid, "mic_mic.wav")
    await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=_bearer(token))
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).refine_status == "pending"
        n = (await db.execute(select(func.count()).select_from(Job).where(Job.type == "meeting_refine"))).scalar_one()
        assert n == 1


async def test_patch_empty_notes_keep_app_notes_when_adopted(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    h = _bearer(token)
    patch = {"notes": [{"at_seconds": 5, "text": "важно"}]}

    # обычная встреча: пустой список очищает
    plain = (await _meeting(client, token))["meeting_id"]
    await client.patch(f"/api/desktop/meetings/{plain}", json=patch, headers=h)
    await client.patch(f"/api/desktop/meetings/{plain}", json={"notes": []}, headers=h)
    async with sm() as db:
        assert (await db.get(MeetingSession, plain)).app_notes is None

    # принятая: пустой список не стирает, непустой заменяет
    mid, _ = await _site_meeting(sm, user, app_notes="[00:05] с сайта")
    assert (await client.post(_url(mid), json=_body(), headers=h)).status_code == 200
    r = await client.patch(f"/api/desktop/meetings/{mid}", json={"notes": []}, headers=h)
    assert r.status_code == 200
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).app_notes == "[00:05] с сайта"
    await client.patch(f"/api/desktop/meetings/{mid}", json=patch, headers=h)
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).app_notes == "[00:05] важно"
