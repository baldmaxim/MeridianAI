"""MeetingRoom-интеграция live multi-channel shadow (Этап 9.6)."""

from types import SimpleNamespace

import pytest

import app.services.meeting_room as mrmod
import app.services.multi_channel_live_session as live_mod
from app.services.meeting_room import MeetingRoom
from app.services.multi_source_ingest import ROLE_PRIMARY, ROLE_SECONDARY
from app.services.multi_channel_live_session import GlobalLiveLimiter


@pytest.fixture(autouse=True)
def _reset_limiter():
    live_mod.live_limiter = GlobalLiveLimiter()
    yield


class FakeProvider:
    request_id = None

    def __init__(self, **kw):
        self.connected = False
        self.closed = False

    async def connect(self, *, channel_count, sample_rate, model, language, on_result, on_error):
        self.connected = True

    async def send_audio(self, pcm):
        pass

    async def keepalive(self):
        pass

    async def close(self, *, finalize=True):
        self.closed = True


class FakeConn:
    def __init__(self, cid, *, can_record=True, clock_quality="good", user_id=1, role="desktop"):
        self.connection_id = cid
        self.user_id = user_id
        self.can_record = can_record
        self.device_role = role
        self.clock = SimpleNamespace(quality=clock_quality) if clock_quality else None
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)

    def to_server_ms(self, x):
        return x


def _room_with_tracks():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    room.api_keys = {"deepgram": "KEY"}
    # ingest: primary "p" + secondary "s", по 5 кадров (общее окно)
    room.ingest.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=b"\x01\x02" * (320 * 5))
    room.ingest.ingest("s", ROLE_SECONDARY, server_ts_ms=100000, arrival_ms=100000,
                       pcm=b"\x03\x04" * (320 * 5), seq=1, side_hint="opponent")
    room.connections = {
        "desk": FakeConn("desk", can_record=True),
        "p": FakeConn("p", clock_quality="good"),
        "s": FakeConn("s", clock_quality="good"),
    }
    return room


def _last_live_state(conn):
    for ev in reversed(conn.sent):
        if ev.get("type") == "multi_channel_live_state":
            return ev
    return None


def _enable(monkeypatch, **over):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "multi_channel_live_enabled", True)
    for k, v in over.items():
        monkeypatch.setattr(s, k, v)
    return s


async def test_permission_denied(monkeypatch):
    _enable(monkeypatch)
    room = _room_with_tracks()
    room.connections["viewer"] = FakeConn("viewer", can_record=False)
    await room._dispatch_client_message("viewer", {
        "type": "multi_channel_live_start", "track_ids": ["p", "s"], "consent_confirmed": True})
    st = _last_live_state(room.connections["viewer"])
    assert st and st["error_code"] == "FORBIDDEN"
    assert room.multi_channel_live is None


async def test_feature_disabled(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "multi_channel_live_enabled", False)
    room = _room_with_tracks()
    await room._dispatch_client_message("desk", {
        "type": "multi_channel_live_start", "track_ids": ["p", "s"], "consent_confirmed": True})
    assert _last_live_state(room.connections["desk"])["error_code"] == "FEATURE_DISABLED"


async def test_consent_required(monkeypatch):
    _enable(monkeypatch)
    room = _room_with_tracks()
    await room._dispatch_client_message("desk", {
        "type": "multi_channel_live_start", "track_ids": ["p", "s"], "consent_confirmed": "true"})
    assert _last_live_state(room.connections["desk"])["error_code"] == "CONSENT_REQUIRED"


async def test_provider_not_configured(monkeypatch):
    _enable(monkeypatch)
    room = _room_with_tracks()
    room.api_keys = {}
    await room._dispatch_client_message("desk", {
        "type": "multi_channel_live_start", "track_ids": ["p", "s"], "consent_confirmed": True})
    assert _last_live_state(room.connections["desk"])["error_code"] == "PROVIDER_NOT_CONFIGURED"


async def test_no_secondary(monkeypatch):
    _enable(monkeypatch)
    room = _room_with_tracks()
    # только primary + ещё один primary
    room.ingest.ingest("p2", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=b"\x01\x02" * (320 * 5))
    room.connections["p2"] = FakeConn("p2", clock_quality="good")
    await room._dispatch_client_message("desk", {
        "type": "multi_channel_live_start", "track_ids": ["p", "p2"], "consent_confirmed": True})
    assert _last_live_state(room.connections["desk"])["error_code"] == "NO_SECONDARY"


async def test_poor_clock_rejected(monkeypatch):
    _enable(monkeypatch)
    room = _room_with_tracks()
    room.connections["s"].clock = SimpleNamespace(quality="poor")
    await room._dispatch_client_message("desk", {
        "type": "multi_channel_live_start", "track_ids": ["p", "s"], "consent_confirmed": True})
    assert _last_live_state(room.connections["desk"])["error_code"] == "CLOCK_QUALITY"


async def test_channel_format_mismatch(monkeypatch):
    _enable(monkeypatch)
    room = _room_with_tracks()
    # secondary "s2" ингестим в float32 → размер кадра не canonical → mux отклоняет
    room.ingest.ingest("s2", ROLE_SECONDARY, server_ts_ms=100000, arrival_ms=100000,
                       pcm=b"\x00" * (320 * 4 * 5), seq=1, channels=1, codec="float32")
    room.connections["s2"] = FakeConn("s2", clock_quality="good")
    await room._dispatch_client_message("desk", {
        "type": "multi_channel_live_start", "track_ids": ["p", "s2"], "consent_confirmed": True})
    assert _last_live_state(room.connections["desk"])["error_code"] == "CHANNEL_FORMAT_MISMATCH"


async def test_successful_start_does_not_touch_primary_stt(monkeypatch):
    _enable(monkeypatch, multi_channel_live_min_prebuffer_ms=0)
    monkeypatch.setattr(mrmod, "DeepgramRealtimeMultichannelProvider", FakeProvider)
    room = _room_with_tracks()
    active_before = room.active_audio_source
    listening_before = room.session.is_listening
    await room._dispatch_client_message("desk", {
        "type": "multi_channel_live_start", "track_ids": ["p", "s"],
        "channel_side_overrides": {"p": "self", "s": "opponent"}, "consent_confirmed": True})
    assert room.multi_channel_live is not None
    assert room.multi_channel_live.state.status in ("streaming", "buffering", "connecting")
    # основной STT/источник не затронуты
    assert room.active_audio_source == active_before
    assert room.session.is_listening == listening_before
    await room.multi_channel_live.stop()
    assert room.multi_channel_live.state.status == "stopped"
