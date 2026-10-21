"""Число говорящих на загрузку (BatchJob.max_speakers) и отдельная копия звука под распознавание."""

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
import requests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.auth.service import hash_password
from app.core.batch import processor as proc
from app.core.batch.audio_compressor import AudioCompressor, build_stt_ffmpeg_args
from app.core.batch.deepgram_transcription_service import DeepgramBatchTranscriptionService
from app.core.batch.gigaam_transcription_service import GigaAMBatchTranscriptionService
from app.core.batch.transcription_service import BatchTranscriptionService
from app.database import Base, get_db
from app.models.batch_job import BatchJob
from app.models.file import FileRecord
from app.models.user import User


# ---------- сервисы ----------

class _OkResp:
    status_code = 200
    text = ""

    def json(self):
        return {"text": "", "words": []}


def _capture_elevenlabs(monkeypatch):
    sent: dict = {}

    def fake_post(url, **kwargs):
        sent.update(kwargs["data"])
        return _OkResp()

    monkeypatch.setattr(requests, "post", fake_post)
    return sent


@pytest.mark.asyncio
async def test_elevenlabs_sends_num_speakers_when_set(monkeypatch, tmp_path):
    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"x")
    sent = _capture_elevenlabs(monkeypatch)
    await BatchTranscriptionService("k", max_speakers=3).transcribe(str(audio))
    assert sent["num_speakers"] == "3"
    assert sent["diarize"] == "true"


@pytest.mark.asyncio
async def test_elevenlabs_no_num_speakers_by_default(monkeypatch, tmp_path):
    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"x")
    sent = _capture_elevenlabs(monkeypatch)
    await BatchTranscriptionService("k").transcribe(str(audio))
    assert "num_speakers" not in sent


def test_all_batch_services_accept_max_speakers():
    for _, cls in proc.BATCH_STT.values():
        assert cls("cred", max_speakers=4).max_speakers == 4
        assert cls("cred").max_speakers is None
    assert DeepgramBatchTranscriptionService("k", max_speakers=2).max_speakers == 2
    assert GigaAMBatchTranscriptionService("http://x", max_speakers=2).max_speakers == 2
    assert list(proc.BATCH_STT) == ["elevenlabs", "deepgram", "gigaam"]


# ---------- ffmpeg-аргументы копии для распознавания ----------

def test_stt_ffmpeg_args_plain():
    args = build_stt_ffmpeg_args("ffmpeg", "/in.mp3", "/out/stt.ogg", "32k", False)
    assert args == ["ffmpeg", "-y", "-threads", "0", "-i", "/in.mp3",
                    "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k", "/out/stt.ogg"]
    assert "-af" not in args


def test_stt_ffmpeg_args_normalize():
    args = build_stt_ffmpeg_args("ffmpeg", "/in.mp3", "/out/stt.ogg", "20k", True)
    i = args.index("-af")
    assert args[i + 1] == "dynaudnorm"
    assert i > args.index("-i") and i < args.index("-ac")
    assert args[-1] == "/out/stt.ogg"


@pytest.mark.asyncio
async def test_prepare_for_stt_without_ffmpeg_returns_none(tmp_path):
    compressor = AudioCompressor()
    compressor.ffmpeg_path = None
    assert await compressor.prepare_for_stt("/in.mp3", str(tmp_path), "20k", True) is None


# ---------- API: валидация и сохранение ----------

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
async def api(sm, tmp_path, monkeypatch):
    from app.api import batch as batch_api
    from app.main import app

    async with sm() as db:
        user = User(email="bm@test.local", password_hash=hash_password("password-1"), role="user")
        db.add(user)
        await db.commit()

    async def _db():
        async with sm() as s:
            yield s
            await s.commit()

    async def _cur():
        return user

    monkeypatch.setattr(batch_api, "get_settings",
                        lambda: SimpleNamespace(upload_dir=str(tmp_path), s3_enabled=True))

    async def _head(key):
        return {"size": 10, "content_type": "audio/ogg"}

    async def _copy(src, dst):
        return None

    monkeypatch.setattr(batch_api.s3, "head_object", _head)
    monkeypatch.setattr(batch_api.s3, "copy_object", _copy)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _cur
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            c.user_id = user.id  # type: ignore[attr-defined]
            c.sm = sm  # type: ignore[attr-defined]
            yield c
    finally:
        app.dependency_overrides.clear()


async def _job_max_speakers(sm, job_id: int):
    async with sm() as db:
        return (await db.get(BatchJob, job_id)).max_speakers


async def _add_file(sm, user_id: int, purpose: str, status: str) -> int:
    async with sm() as db:
        rec = FileRecord(user_id=user_id, object_key=f"k/{purpose}/a.mp3", original_name="a.mp3",
                         size=10, purpose=purpose, status=status)
        db.add(rec)
        await db.commit()
        return rec.id


@pytest.mark.parametrize("value", ["2", "6"])
async def test_upload_accepts_valid_max_speakers(api, value):
    r = await api.post("/api/batch/upload", files={"file": ("a.mp3", b"x")}, data={"max_speakers": value})
    assert r.status_code == 200, r.text
    assert r.json()["max_speakers"] == int(value)
    assert await _job_max_speakers(api.sm, r.json()["id"]) == int(value)


@pytest.mark.parametrize("value", ["1", "7", "x"])
async def test_upload_rejects_invalid_max_speakers(api, value):
    r = await api.post("/api/batch/upload", files={"file": ("a.mp3", b"x")}, data={"max_speakers": value})
    assert r.status_code == 422


async def test_upload_without_max_speakers_is_auto(api):
    r = await api.post("/api/batch/upload", files={"file": ("a.mp3", b"x")})
    assert r.status_code == 200, r.text
    assert r.json()["max_speakers"] is None


async def test_confirm_saves_max_speakers(api):
    fid = await _add_file(api.sm, api.user_id, "batch_audio", "pending")
    r = await api.post(f"/api/batch/confirm/{fid}", json={"max_speakers": 4})
    assert r.status_code == 200, r.text
    assert await _job_max_speakers(api.sm, r.json()["id"]) == 4


@pytest.mark.parametrize("value", [1, 7, "x"])
async def test_confirm_rejects_invalid_max_speakers(api, value):
    fid = await _add_file(api.sm, api.user_id, "batch_audio", "pending")
    r = await api.post(f"/api/batch/confirm/{fid}", json={"max_speakers": value})
    assert r.status_code == 422


async def test_confirm_without_body_is_auto(api):
    fid = await _add_file(api.sm, api.user_id, "batch_audio", "pending")
    r = await api.post(f"/api/batch/confirm/{fid}")
    assert r.status_code == 200, r.text
    assert r.json()["max_speakers"] is None


async def test_from_stash_saves_max_speakers(api):
    fid = await _add_file(api.sm, api.user_id, "stash", "active")
    r = await api.post(f"/api/batch/from-stash/{fid}", json={"max_speakers": 5})
    assert r.status_code == 200, r.text
    assert await _job_max_speakers(api.sm, r.json()["id"]) == 5


async def test_from_stash_without_body_and_invalid(api):
    fid = await _add_file(api.sm, api.user_id, "stash", "active")
    assert (await api.post(f"/api/batch/from-stash/{fid}", json={"max_speakers": 7})).status_code == 422
    r = await api.post(f"/api/batch/from-stash/{fid}")
    assert r.status_code == 200, r.text
    assert r.json()["max_speakers"] is None


# ---------- processor ----------

class _FakeService:
    calls: list = []

    def __init__(self, credential, max_speakers=None):
        self.max_speakers = max_speakers

    async def transcribe(self, file_path):
        _FakeService.calls.append((self.max_speakers, file_path))
        return {"text": "ok", "words": []}


@pytest_asyncio.fixture
async def run_job(sm, tmp_path, monkeypatch):
    """Запускает handle_batch_transcribe над одной задачей с подменёнными зависимостями."""
    _FakeService.calls = []

    async def _keys():
        return {"deepgram": "dg"}

    async def _user_settings(uid):
        return {"stt_provider": "deepgram", "diarization_max_speakers": 9}

    monkeypatch.setattr(proc, "async_session", sm)
    monkeypatch.setattr(proc, "load_api_keys", _keys)
    monkeypatch.setattr(proc, "load_user_settings", _user_settings)
    monkeypatch.setitem(proc.BATCH_STT, "deepgram", ("Deepgram", _FakeService))

    async def _run(max_speakers, bitrate="20k", normalize=False):
        monkeypatch.setattr(proc, "get_settings", lambda: SimpleNamespace(
            s3_enabled=False, gigaam_url="", batch_stt_bitrate=bitrate, batch_stt_normalize=normalize))
        audio = tmp_path / "rec.ogg"
        audio.write_bytes(b"x")
        async with sm() as db:
            user = User(email=f"p{max_speakers}{bitrate}{normalize}@t.local",
                        password_hash=hash_password("password-1"), role="user")
            db.add(user)
            await db.flush()
            job = BatchJob(user_id=user.id, status="uploaded", original_filename="rec.ogg",
                           original_size=1, file_path=str(audio), max_speakers=max_speakers)
            db.add(job)
            await db.commit()
            job_id = job.id
        await proc.handle_batch_transcribe({"batch_job_id": job_id})
        async with sm() as db:
            return (await db.execute(select(BatchJob).where(BatchJob.id == job_id))).scalar_one(), str(audio)

    return _run


async def test_processor_passes_job_max_speakers(run_job):
    job, audio = await run_job(3)
    assert job.status == "done"
    assert _FakeService.calls == [(3, audio)]  # не diarization_max_speakers из настроек


async def test_processor_auto_when_not_set(run_job):
    await run_job(None)
    assert _FakeService.calls[0][0] is None


async def test_processor_default_flags_do_not_reencode(run_job, monkeypatch):
    async def boom(self, *a, **k):
        raise AssertionError("prepare_for_stt не должен вызываться")

    monkeypatch.setattr(AudioCompressor, "prepare_for_stt", boom)
    job, audio = await run_job(None)
    assert _FakeService.calls == [(None, audio)]


async def test_processor_uses_stt_copy_when_flag_set(run_job, monkeypatch):
    seen = {}

    async def fake_prepare(self, input_path, output_dir, bitrate, normalize):
        seen.update(input=input_path, bitrate=bitrate, normalize=normalize)
        return "/tmp/fake/stt.ogg"

    monkeypatch.setattr(AudioCompressor, "is_available", property(lambda self: True))
    monkeypatch.setattr(AudioCompressor, "prepare_for_stt", fake_prepare)
    job, audio = await run_job(None, bitrate="32k", normalize=True)
    assert seen == {"input": audio, "bitrate": "32k", "normalize": True}
    assert _FakeService.calls == [(None, "/tmp/fake/stt.ogg")]
    assert job.status == "done"


async def test_processor_falls_back_when_stt_copy_fails(run_job, monkeypatch):
    async def failing(self, *a, **k):
        return None

    monkeypatch.setattr(AudioCompressor, "is_available", property(lambda self: True))
    monkeypatch.setattr(AudioCompressor, "prepare_for_stt", failing)
    job, audio = await run_job(None, normalize=True)
    assert _FakeService.calls == [(None, audio)]
    assert job.status == "done"
