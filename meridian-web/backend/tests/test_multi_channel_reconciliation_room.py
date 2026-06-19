"""MeetingRoom-интеграция channel-aware reconciliation (Этап 9.7)."""

import asyncio
from collections import deque
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.services.multi_channel_live_session as live_mod
from app.core.transcription.models import CommittedSegment
from app.services.meeting_room import MeetingRoom
from app.services.realtime_multi_channel_mux import RealtimeMuxChannel
from app.services.multi_channel_live_session import (
    MultiChannelLiveSession, LiveMultiChannelSegment, GlobalLiveLimiter,
)


@pytest.fixture(autouse=True)
def _reset_limiter():
    live_mod.live_limiter = GlobalLiveLimiter()
    yield


class FakeConn:
    def __init__(self, cid="desk"):
        self.connection_id = cid
        self.user_id = 1
        self.can_record = True
        self.device_role = "desktop"
        self.clock = SimpleNamespace(quality="good")
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)

    def to_server_ms(self, x):
        return x


class FakeProvider:
    request_id = None

    async def connect(self, **kw):
        pass

    async def send_audio(self, pcm):
        pass

    async def keepalive(self):
        pass

    async def close(self, *, finalize=True):
        pass


def _channels():
    return (
        RealtimeMuxChannel(0, "p", "p", 0, "primary", "Основной канал", "self"),
        RealtimeMuxChannel(1, "s", "s", 0, "secondary", "Shadow — Не мы", "opponent"),
    )


def _make_live(room):
    from app.config import get_settings
    sess = MultiChannelLiveSession(
        meeting_id=1, owner_user_id=1, ingest=room.ingest, broadcast=room.broadcast,
        provider=FakeProvider(), channels=_channels(), settings=get_settings())
    sess.state.start_server_ms = 0
    sess.state.status = "streaming"          # активная сессия (gate _live_is_active)
    sess.state.silence_ratio_by_channel = [0.0, 0.0]
    sess.state.final_segments = deque(maxlen=2000)
    return sess


def _committed(room, key, text, start_ms, dur_ms=1000):
    # подобрать wall_clock так, чтобы server_ts_ms == start_ms
    wc = datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc)
    return CommittedSegment(segment_id=key, text=text, start_time=0.0, end_time=dur_ms / 1000.0,
                            wall_clock=wc)


def _channel_final(sess, sid, ci, text, start_ms, end_ms, side="opponent"):
    return LiveMultiChannelSegment(
        segment_id=sid, session_id=sess.session_id, channel_index=ci, channels_count=2,
        track_id=f"t{ci}", channel_label="ch", side=side, transcript=text, confidence=0.9,
        provider_start=0.0, provider_end=(end_ms - start_ms) / 1000.0,
        start_server_ms=start_ms, end_server_ms=end_ms, is_final=True, speech_final=True, words=())


def _last(conn, mtype):
    for ev in reversed(conn.sent):
        if ev.get("type") == mtype:
            return ev
    return None


async def test_refresh_builds_state_and_broadcasts():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    conn = FakeConn()
    room.connections = {"desk": conn}
    sess = _make_live(room)
    seg = _committed(room, "p0", "привет мир", 100000)
    start_ms = seg.server_ts_ms
    room.session._committed_segments.append(seg)
    sess.state.final_segments.append(_channel_final(sess, "c0", 1, "привет мир", start_ms, start_ms + 1000))
    room.multi_channel_live = sess

    before_segments = list(room.session._committed_segments)
    before_corr = dict(room.session.speaker_segment_corrections)

    await room._refresh_multi_channel_reconciliation(reason="test")

    assert room.multi_channel_reconciliation is not None
    ev = _last(conn, "multi_channel_reconciliation_state")
    assert ev is not None and ev["state"]["summary"]["matched"] == 1
    e0 = ev["state"]["entries"][0]
    assert e0["kind"] == "matched" and e0["side_agreement"] == "suggested"
    # чтение не мутирует session committed/corrections
    assert list(room.session._committed_segments) == before_segments
    assert dict(room.session.speaker_segment_corrections) == before_corr


async def test_on_live_final_segment_schedules(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "multi_channel_reconciliation_refresh_ms", 100)
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    room.connections = {"desk": FakeConn()}
    sess = _make_live(room)
    seg = _committed(room, "p0", "привет мир", 100000)
    room.session._committed_segments.append(seg)
    sess.state.final_segments.append(
        _channel_final(sess, "c0", 1, "привет мир", seg.server_ts_ms, seg.server_ts_ms + 1000))
    room.multi_channel_live = sess

    await room._on_live_final_segment(None)        # планирует debounced refresh
    assert room._reconciliation_task is not None
    await asyncio.sleep(0.2)
    assert room.multi_channel_reconciliation is not None
    assert room._reconciliation_revision >= 1


async def test_clear_removes_reconciliation():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    room.connections = {"desk": FakeConn()}
    sess = _make_live(room)
    seg = _committed(room, "p0", "текст", 100000)
    room.session._committed_segments.append(seg)
    sess.state.final_segments.append(
        _channel_final(sess, "c0", 1, "текст", seg.server_ts_ms, seg.server_ts_ms + 1000))
    room.multi_channel_live = sess
    await room._refresh_multi_channel_reconciliation(reason="test")
    assert room.multi_channel_reconciliation is not None
    await room._clear_multi_channel_reconciliation()
    assert room.multi_channel_reconciliation is None


async def test_snapshot_event_null_when_absent():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    ev = room._reconciliation_snapshot_event()
    assert ev["type"] == "multi_channel_reconciliation_snapshot" and ev["state"] is None


async def test_stopped_live_session_not_refreshed():
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    room.connections = {"desk": FakeConn()}
    sess = _make_live(room)
    sess.state.status = "stopped"      # терминальная → не рефрешим
    room.multi_channel_live = sess
    await room._schedule_multi_channel_reconciliation(reason="committed")
    assert room._reconciliation_task is None
    await room._refresh_multi_channel_reconciliation(reason="committed")
    assert room.multi_channel_reconciliation is None


async def test_disabled_skips(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "multi_channel_reconciliation_enabled", False)
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    room.connections = {"desk": FakeConn()}
    room.multi_channel_live = _make_live(room)
    await room._schedule_multi_channel_reconciliation(reason="x")
    assert room._reconciliation_task is None
