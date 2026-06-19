"""API-тесты batch multi-channel STT (Этап 9.5) — dependency overrides + fake room, без БД/сети."""

from types import SimpleNamespace

import pytest

from app.services.multi_source_ingest import MultiSourceIngest, ROLE_PRIMARY, ROLE_SECONDARY
from app.services.multi_channel_batch_jobs import MultiChannelBatchJobRegistry
from app.services.multi_channel_batch_stt import (
    MultiChannelBatchResult, MultiChannelBatchChannel,
)

SPF = 320


def _ingest_settings():
    return SimpleNamespace(multi_source_ingest_enabled=True, multi_source_ingest_frame_ms=20,
                           multi_source_ingest_window_seconds=8, multi_source_ingest_max_tracks=6)


def _pcm(n):
    return bytes(i % 256 for i in range(n))


class _FakeProvider:
    name = "deepgram"

    def __init__(self, **kw):
        pass

    async def transcribe(self, *, wav_bytes, channel_count, channel_mapping,
                         language, model, timeout_seconds):
        chans = tuple(MultiChannelBatchChannel(
            channel_index=m["channel_index"], track_id=m["track_id"],
            channel_label=m["channel_label"], side=m["side"], source_kind=m["source_kind"],
            generation=m["generation"], transcript="ок", words_count=0, segments_count=0,
            average_confidence=0.9, segments=(), warnings=()) for m in channel_mapping)
        return MultiChannelBatchResult(
            provider="deepgram", model=model, language=language, provider_request_id="req",
            sample_rate=16000, channels_count=channel_count, duration_ms=100,
            channels=chans, chronological_segments=(), combined_text="", warnings=(),
            provider_meta={"request_id": "req"})


@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.dependencies import get_current_user
    from app.database import get_db
    from app.config import get_settings
    from app.services import meeting_room as mrmod
    import app.api.multi_channel_batch_stt as mod

    state = SimpleNamespace(meeting_exists=True, user_id=1)

    class FakeUser:
        def __init__(self, uid):
            self.id = uid
            self.role = "admin"
            self.is_active = True

    class FakeDB:
        async def get(self, model, pk):
            return object() if state.meeting_exists else None

    async def _db():
        yield FakeDB()

    app.dependency_overrides[get_current_user] = lambda: FakeUser(state.user_id)
    app.dependency_overrides[get_db] = _db

    # включить фичу + убрать min-duration (короткое тестовое окно)
    s = get_settings()
    monkeypatch.setattr(s, "multi_channel_batch_stt_enabled", True)
    monkeypatch.setattr(s, "multi_channel_batch_stt_min_duration_seconds", 0)

    # fake provider + свежий registry + key resolver
    monkeypatch.setattr(mod, "DeepgramMultiChannelBatchProvider", _FakeProvider)
    monkeypatch.setattr(mod, "batch_job_registry", MultiChannelBatchJobRegistry())

    async def _keys():
        return {"deepgram": "KEY"} if state.provider_key else {}
    state.provider_key = True
    monkeypatch.setattr(mod, "load_api_keys", _keys)

    ing = MultiSourceIngest(_ingest_settings())
    ing.ingest("a", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=_pcm(SPF * 2 * 5))
    ing.ingest("b", ROLE_SECONDARY, server_ts_ms=100000, arrival_ms=100000,
               pcm=_pcm(SPF * 2 * 5), seq=1, side_hint="opponent")
    session = SimpleNamespace(
        committed_segments=[SimpleNamespace(text="привет мир", segment_id="x")],
        _resolve_segment=lambda seg: ("spk", "self"),
    )
    state.room = SimpleNamespace(ingest=ing, connections={}, active_audio_source="a", session=session)
    monkeypatch.setattr(mrmod.room_registry, "get_room", lambda mid: state.room)

    state.client = TestClient(app)
    state.ingest = ing
    try:
        yield state
    finally:
        app.dependency_overrides.clear()


def _body(track_ids=("a", "b"), **extra):
    return {"export": {"window_mode": "last", "track_ids": list(track_ids), **extra}}


def test_disabled_503(api, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "multi_channel_batch_stt_enabled", False)
    r = api.client.post("/api/meetings/1/multi-source/batch-stt", json=_body())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "FEATURE_DISABLED"


def test_provider_not_configured_503(api):
    api.provider_key = False
    r = api.client.post("/api/meetings/1/multi-source/batch-stt", json=_body())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "PROVIDER_NOT_CONFIGURED"


def test_meeting_404(api):
    api.meeting_exists = False
    r = api.client.post("/api/meetings/1/multi-source/batch-stt", json=_body())
    assert r.status_code == 404


def test_no_room_409(api):
    api.room = None
    r = api.client.post("/api/meetings/1/multi-source/batch-stt", json=_body())
    assert r.status_code == 409


def test_fewer_than_two_channels_422(api):
    r = api.client.post("/api/meetings/1/multi-source/batch-stt", json=_body(track_ids=("a",)))
    assert r.status_code == 422


def test_invalid_override_422(api):
    body = _body()
    body["channel_side_overrides"] = {"zzz": "self"}   # не из selected
    r = api.client.post("/api/meetings/1/multi-source/batch-stt", json=body)
    assert r.status_code == 422


def test_post_202_and_get_and_delete(api):
    before = (api.ingest.tracks["a"].frames_count, list(api.ingest.tracks["a"].order))
    r = api.client.post("/api/meetings/1/multi-source/batch-stt", json=_body())
    assert r.status_code == 202
    job = r.json()
    assert job["job_id"] and job["meeting_id"] == 1
    assert "result" in job
    # ingest НЕ мутирован обработкой
    after = (api.ingest.tracks["a"].frames_count, list(api.ingest.tracks["a"].order))
    assert before == after

    jid = job["job_id"]
    g = api.client.get(f"/api/meetings/1/multi-source/batch-stt/{jid}")
    assert g.status_code == 200 and g.json()["job_id"] == jid

    d = api.client.delete(f"/api/meetings/1/multi-source/batch-stt/{jid}")
    assert d.status_code == 200 and d.json()["cancelled"] is True


def test_get_unknown_job_404(api):
    r = api.client.get("/api/meetings/1/multi-source/batch-stt/nope")
    assert r.status_code == 404
