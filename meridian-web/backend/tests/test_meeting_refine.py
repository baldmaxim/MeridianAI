# -*- coding: utf-8 -*-
"""Уточнение десктоп-встреч: сопоставление голосов, сторона по каналам, триггер финализации, job-обработчик."""

import json
import wave
from datetime import timedelta

import numpy as np
from sqlalchemy import select

from app.config import get_settings
from app.core.meeting_refine import handler as refine
from app.core.meeting_refine.audio import load_wav_energy, wav_duration
from app.core.meeting_refine.mapping import (
    Span, dominant_side, map_speakers, next_voice_number, window_energy,
)
from app.models.directory import Customer, ProjectObject
from app.models.file import FileRecord
from app.models.job import Job
from app.models.knowledge import GlossaryTerm
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.meeting_conversation import MeetingSpeakerRole
from app.services import s3 as s3mod
from app.services.meeting_finalize import _gather_inputs, _speaker_title
from app.services.speaker_roles import upsert_role

from .test_desktop_api import _bearer, _device, _meeting, _seg, _user, client, sm  # noqa: F401


# ---------- сопоставление голосов ----------

def test_map_speakers_by_overlap_one_to_one():
    refined = [Span("A", 0, 10), Span("B", 10, 20)]
    draft = [Span("Голос 1", 0, 9), Span("Голос 2", 11, 20)]
    assert map_speakers(refined, draft) == {"A": "Голос 1", "B": "Голос 2"}


def test_map_speakers_greedy_by_descending_overlap():
    # A пересекается с обеими метками, но с «Голос 2» сильнее; B достаётся «Голос 1»
    refined = [Span("A", 0, 10), Span("B", 10, 14)]
    draft = [Span("Голос 1", 8, 14), Span("Голос 2", 0, 10)]
    assert map_speakers(refined, draft) == {"A": "Голос 2", "B": "Голос 1"}


def test_map_speakers_threshold_gives_new_label():
    # общее пересечение 2 с на 10 с речи — 20% < 30%
    refined = [Span("A", 0, 10)]
    draft = [Span("Голос 1", 8, 10), Span("Голос 3", 50, 60)]
    assert map_speakers(refined, draft) == {"A": "Голос 4"}


def test_map_speakers_new_labels_in_order_of_appearance():
    refined = [Span("X", 5, 6), Span("Y", 0, 1)]
    assert map_speakers(refined, []) == {"Y": "Голос 1", "X": "Голос 2"}


def test_map_speakers_one_label_not_shared_by_two_voices():
    refined = [Span("A", 0, 10), Span("B", 0, 10)]
    draft = [Span("Мы", 0, 10)]
    got = map_speakers(refined, draft)
    assert sorted(got.values()) == ["Голос 1", "Мы"]


def test_map_speakers_works_with_side_labels():
    refined = [Span("A", 0, 5), Span("B", 5, 10)]
    draft = [Span("Мы", 0, 5), Span("Оппонент", 5, 10)]
    assert map_speakers(refined, draft) == {"A": "Мы", "B": "Оппонент"}


def test_next_voice_number():
    assert next_voice_number(["Мы", "Голос 2", "Голос 10"]) == 11
    assert next_voice_number([]) == 1


# ---------- сторона по каналам ----------

def test_dominant_side_on_synthetic_energy():
    sr, w = 16000, 0.1
    frames = int(sr * w)
    mic = np.concatenate([np.full(frames * 10, 8000), np.zeros(frames * 10)])
    system = np.concatenate([np.full(frames * 10, 500), np.full(frames * 10, 8000)])
    me, se = window_energy(mic, frames), window_energy(system, frames)
    assert dominant_side(me, se, 0.0, 1.0) == "self"
    assert dominant_side(me, se, 1.0, 2.0) == "opponent"
    assert dominant_side(me, se, 100.0, 101.0) is None  # вне записи
    silent = window_energy(np.zeros(frames * 5), frames)
    assert dominant_side(silent, silent, 0.0, 0.5) is None


def _write_wav(path, samples: np.ndarray, rate=16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())


def test_load_wav_energy_and_duration(tmp_path):
    p = tmp_path / "a.wav"
    _write_wav(p, np.concatenate([np.full(16000, 1000), np.zeros(16000)]))
    energy = load_wav_energy(str(p))
    assert energy is not None and len(energy) == 20
    assert energy[:10].mean() > 0 and energy[10:].sum() == 0
    assert wav_duration(str(p)) == 2.0
    bad = tmp_path / "b.ogg"
    bad.write_bytes(b"not a wav")
    assert load_wav_energy(str(bad)) is None and wav_duration(str(bad)) is None


# ---------- подписи спикеров в протоколе ----------

def test_speaker_title():
    roles = {"Голос 2": "opponent", "Голос 1": "self", "Мы": "self"}
    names = {"Голос 1": "Иван Петров"}
    assert _speaker_title("Голос 1", roles, names) == "Иван Петров"
    assert _speaker_title("Голос 2", roles, names) == "Голос 2 (оппонент)"
    assert _speaker_title("Мы", roles, names) == "Мы"
    assert _speaker_title("Голос 3", roles, names) == "Голос 3"


async def test_protocol_inputs_use_roles(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token, "in_person"))["meeting_id"]
    await client.put(f"/api/desktop/meetings/{mid}/segments", headers=_bearer(token), json={"segments": [
        _seg("a", "Привет", 0, 1, speaker_label="Голос 1"),
        _seg("b", "Здравствуйте", 2, 3, speaker_label="Голос 2"),
        _seg("c", "Тоже здесь", 4, 5, speaker_label="Голос 3"),
    ]})
    async with sm() as db:
        await upsert_role(db, mid, "Голос 1", side="self", display_name="Иван")
        await upsert_role(db, mid, "Голос 2", side="opponent")
        await db.commit()
        meeting = await db.get(MeetingSession, mid)
        _, transcript, _, _ = await _gather_inputs(db, meeting)
    assert "Иван: Привет" in transcript
    assert "Голос 2 (оппонент): Здравствуйте" in transcript
    assert "Голос 3: Тоже здесь" in transcript


# ---------- триггер: finalize десктопа ----------

async def _add_audio(sm, mid, user_id, name="mic_mic.wav", status="active"):
    async with sm() as db:
        db.add(FileRecord(user_id=user_id, object_key=f"u/{mid}/{name}", original_name=name,
                          purpose="meeting_audio", status=status, meeting_id=mid))
        await db.commit()


async def _jobs(sm, type_):
    async with sm() as db:
        return (await db.execute(select(Job).where(Job.type == type_))).scalars().all()


async def test_finalize_with_audio_enqueues_refine_instead_of_finalize(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    await _add_audio(sm, mid, user.id)
    h = _bearer(token)
    assert (await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)).status_code == 200
    assert (await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=h)).status_code == 200

    refine_jobs = await _jobs(sm, "meeting_refine")
    assert len(refine_jobs) == 1 and refine_jobs[0].payload == {"meeting_id": mid}
    assert await _jobs(sm, "meeting_finalize") == []
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.refine_status == "pending" and m.status == "finalized" and m.is_active is False
        assert m.finalization_status == "not_started"


async def test_finalize_without_audio_is_skipped(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    await _add_audio(sm, mid, user.id, status="pending")  # не подтверждённый файл не считается
    await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=_bearer(token))
    assert await _jobs(sm, "meeting_refine") == []
    assert len(await _jobs(sm, "meeting_finalize")) == 1
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).refine_status == "skipped"


async def test_finalize_with_refine_disabled_is_skipped(sm, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "desktop_refine_enabled", False)
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    await _add_audio(sm, mid, user.id)
    await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=_bearer(token))
    assert await _jobs(sm, "meeting_refine") == []
    assert len(await _jobs(sm, "meeting_finalize")) == 1
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).refine_status == "skipped"


# ---------- upsert и просмотр ----------

async def test_upsert_stores_max_speakers(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    cu = "11111111-1111-4111-8111-111111111111"
    mid = (await _meeting(client, token, client_uuid=cu, max_speakers=4))["meeting_id"]
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).diarization_max_speakers == 4
    await _meeting(client, token, client_uuid=cu)  # без поля — не меняется
    async with sm() as db:
        assert (await db.get(MeetingSession, mid)).diarization_max_speakers == 4
    r = await client.post("/api/desktop/meetings", headers=_bearer(token), json={
        "client_uuid": cu, "title": "x", "started_at": "2026-10-21T09:00:00+00:00",
        "capture_mode": "online", "max_speakers": 1})
    assert r.status_code == 422


async def test_view_and_library_expose_refine_status(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        m.refine_status, m.refine_error = "failed", "Нет ключа"
        await db.commit()
    h = _bearer(token)
    view = (await client.get(f"/api/desktop/meetings/{mid}/view", headers=h)).json()
    assert view["refine_status"] == "failed" and view["refine_error"] == "Нет ключа"
    item = next(i for i in (await client.get("/api/desktop/library", headers=h)).json() if i["meeting_id"] == mid)
    assert item["refine_status"] == "failed"


# ---------- обработчик job ----------

class _FakeService:
    """Подмена BatchTranscriptionService: отдаёт заданный ответ, запоминает параметры."""

    result: dict | None = None
    calls: list[dict] = []

    def __init__(self, api_key, max_speakers=None, keyterms=None):
        type(self).calls.append({"max_speakers": max_speakers, "keyterms": keyterms})

    async def transcribe(self, path, timeout=600):
        return type(self).result


def _words(speaker, start, texts, step=0.5):
    return [{"text": t, "start": start + i * step, "end": start + i * step + 0.4, "speaker_id": speaker}
            for i, t in enumerate(texts)]


async def _setup_online_meeting(sm, client, monkeypatch, tmp_path):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = (await _meeting(client, token, max_speakers=3))["meeting_id"]
    h = _bearer(token)
    await client.put(f"/api/desktop/meetings/{mid}/segments", headers=h, json={"segments": [
        _seg("a", "черновик раз", 0.0, 4.0, channel="mic", speaker_label="Голос 1"),
        _seg("b", "черновик два", 5.0, 9.0, channel="system", speaker_label="Голос 2"),
    ]})
    await _add_audio(sm, mid, user.id, "mic_mic.wav")
    await _add_audio(sm, mid, user.id, "system_system.wav")
    async with sm() as db:
        await upsert_role(db, mid, "Голос 1", side=None, display_name="Иван")  # имя без стороны
        await upsert_role(db, mid, "Голос 2", side="self")  # выбор пользователя против громкости
        meeting = await db.get(MeetingSession, mid)
        db.add(Customer(name="ООО Заказчик"))
        await db.flush()
        cust = (await db.execute(select(Customer))).scalars().first()
        obj = ProjectObject(name="ЖК Север", customer_id=cust.id)
        db.add(obj)
        await db.flush()
        meeting.customer_id, meeting.object_id = cust.id, obj.id
        db.add(GlossaryTerm(owner_user_id=user.id, customer_id=cust.id, term="КС-2", definition="акт"))
        await db.commit()

    async def _download(key, dest):
        loud, quiet = np.full(160000, 8000), np.full(160000, 300)
        mic = np.concatenate([loud[:80000], quiet[:80000]])  # 0–5 с громко, дальше тихо
        system = np.concatenate([quiet[:80000], loud[:80000]])
        _write_wav(dest, mic if "mic_" in key else system)

    async def _prepare(paths, tmpdir):
        return paths[0]

    async def _keys():
        return {"elevenlabs": "test-key"}

    monkeypatch.setattr(type(get_settings()), "s3_enabled", property(lambda self: True))
    monkeypatch.setattr(s3mod, "download_to", _download)
    monkeypatch.setattr(refine, "prepare_audio", _prepare)
    monkeypatch.setattr(refine, "load_api_keys", _keys)
    monkeypatch.setattr(refine, "async_session", sm)
    monkeypatch.setattr(refine, "BatchTranscriptionService", _FakeService)
    _FakeService.calls = []
    _FakeService.result = {"text": "", "words": (
        _words("Speaker_0", 0.2, ["Добрый", "день", "коллеги"]) +
        _words("Speaker_1", 5.2, ["Здравствуйте", "начнём", "обсуждение"]) +
        _words("Speaker_2", 9.4, ["Я", "из", "бухгалтерии"], step=0.1)
    )}
    return mid


async def test_handler_replaces_transcript_and_requests_finalization(sm, client, monkeypatch, tmp_path):
    mid = await _setup_online_meeting(sm, client, monkeypatch, tmp_path)
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        m.status, m.refine_status = "finalized", "pending"
        await db.commit()

    await refine.handle_meeting_refine({"meeting_id": mid})

    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.refine_status == "done" and m.refine_error is None and m.refined_at is not None
        draft = json.loads(m.transcript_draft_json)
        assert [d["text"] for d in draft] == ["черновик раз", "черновик два"]
        assert draft[0]["segment_id"] and draft[0]["speaker_label"] == "Голос 1"
        segs = (await db.execute(
            select(TranscriptSegmentRecord).where(TranscriptSegmentRecord.session_id == mid)
            .order_by(TranscriptSegmentRecord.start_time)
        )).scalars().all()
        assert [s.origin for s in segs] == ["refined"] * 3
        assert [s.speaker_label for s in segs] == ["Голос 1", "Голос 2", "Голос 3"]
        assert segs[0].text == "Добрый день коллеги"
        assert segs[0].wall_clock == m.started_at + timedelta(seconds=segs[0].start_time)
        assert len({s.segment_id for s in segs}) == 3
        # сторона по громкости: 0–5 с слышен микрофон, дальше — звук встречи
        assert [s.speaker_id for s in segs[:2]] == ["desktop_mic", "desktop_system"]
        roles = {r.speaker_label: (r.side, r.display_name) for r in
                 (await db.execute(select(MeetingSpeakerRole).where(MeetingSpeakerRole.meeting_id == mid)))
                 .scalars().all()}
        assert roles["Голос 1"] == ("self", "Иван")  # сторона дозаполнена, имя не тронуто
        assert roles["Голос 2"][0] == "self"  # выбор пользователя не перезаписан
        assert roles["Голос 3"][0] == "opponent"
    assert len(await _jobs(sm, "meeting_finalize")) == 1

    call = _FakeService.calls[0]
    assert call["max_speakers"] == 3
    assert call["keyterms"][:3] == ["ООО Заказчик", "ЖК Север", "КС-2"] and "Иван" in call["keyterms"]

    await refine.handle_meeting_refine({"meeting_id": mid})  # повтор job-а: протокол не дублируется
    assert len(await _jobs(sm, "meeting_finalize")) == 1


async def test_handler_failure_keeps_draft_and_still_finalizes(sm, client, monkeypatch, tmp_path):
    mid = await _setup_online_meeting(sm, client, monkeypatch, tmp_path)
    _FakeService.result = None

    await refine.handle_meeting_refine({"meeting_id": mid})

    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.refine_status == "failed" and "ElevenLabs" in m.refine_error
        assert m.transcript_draft_json is None
        segs = (await db.execute(
            select(TranscriptSegmentRecord).where(TranscriptSegmentRecord.session_id == mid)
        )).scalars().all()
        assert sorted(s.text for s in segs) == ["черновик два", "черновик раз"]
        assert {s.origin for s in segs} == {"desktop"}
    assert len(await _jobs(sm, "meeting_finalize")) == 1


async def test_handler_without_api_key_fails_softly(sm, client, monkeypatch, tmp_path):
    mid = await _setup_online_meeting(sm, client, monkeypatch, tmp_path)

    async def _no_keys():
        return {}

    monkeypatch.setattr(refine, "load_api_keys", _no_keys)
    await refine.handle_meeting_refine({"meeting_id": mid})
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.refine_status == "failed" and "ключ" in m.refine_error
    assert len(await _jobs(sm, "meeting_finalize")) == 1


async def test_handler_rejects_too_long_recording(sm, client, monkeypatch, tmp_path):
    mid = await _setup_online_meeting(sm, client, monkeypatch, tmp_path)
    monkeypatch.setattr(get_settings(), "desktop_refine_max_hours", 0.0001)  # 0,36 с
    await refine.handle_meeting_refine({"meeting_id": mid})
    async with sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.refine_status == "failed" and "длиннее" in m.refine_error
    assert _FakeService.calls == []


def test_channel_of():
    assert refine.channel_of("mic_mic.wav") == "mic"
    assert refine.channel_of("System_x.wav") == "system"
    assert refine.channel_of("meeting_5.ogg") is None


