"""Тесты multi-channel live STT shadow session (Этап 9.6)."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services.multi_source_ingest import MultiTrackFrameRead
from app.services.realtime_multi_channel_mux import RealtimeMuxChannel
from app.services.realtime_multi_channel_provider import (
    RealtimeMultiChannelProviderError, RealtimeProviderResult,
)
import app.services.multi_channel_live_session as live_mod
from app.services.multi_channel_live_session import MultiChannelLiveSession, GlobalLiveLimiter

FRAME_MS = 20


@pytest.fixture(autouse=True)
def _reset_limiter():
    live_mod.live_limiter = GlobalLiveLimiter()
    yield


def make_settings(**over):
    base = dict(
        multi_channel_live_provider="deepgram", multi_channel_live_model="nova-3",
        multi_channel_live_language="ru", multi_channel_live_playout_delay_ms=500,
        multi_channel_live_send_chunk_ms=100, multi_channel_live_send_queue_chunks=30,
        multi_channel_live_min_prebuffer_ms=1000, multi_channel_live_start_timeout_seconds=5,
        multi_channel_live_close_timeout_seconds=5, multi_channel_live_keepalive_seconds=4,
        multi_channel_live_interim_broadcast_ms=0, multi_channel_live_state_broadcast_ms=1000,
        multi_channel_live_max_final_segments=2000, multi_channel_live_max_session_seconds=7200,
        multi_channel_live_track_stale_grace_ms=3000,
        multi_channel_live_secondary_silence_stop_ms=15000,
        multi_channel_live_max_global_sessions=8,
        multi_source_ingest_frame_ms=FRAME_MS, secondary_audio_shadow_target_sample_rate=16000,
    )
    base.update(over)
    return SimpleNamespace(**base)


class FakeIngest:
    def __init__(self, frames):
        self.frames = frames
        self.frame_ms = FRAME_MS

    def read_tracks_at_index(self, *, track_ids, frame_index):
        out = [(tid, self.frames.get(tid, {}).get(frame_index)) for tid in track_ids]
        return MultiTrackFrameRead(frame_index, frame_index * FRAME_MS,
                                   (frame_index + 1) * FRAME_MS, tuple(out))

    def get_common_range(self, track_ids):
        rs = []
        for tid in track_ids:
            f = self.frames.get(tid)
            if not f:
                return (None, None)
            rs.append((min(f), max(f)))
        lo, hi = max(r[0] for r in rs), min(r[1] for r in rs)
        return (lo, hi) if lo <= hi else (None, None)

    def get_track_range(self, tid):
        f = self.frames.get(tid)
        return (min(f), max(f)) if f else (None, None)


class FakeProvider:
    request_id = None

    def __init__(self, connect_error=None):
        self.connect_error = connect_error
        self.connected = False
        self.closed = False
        self.sent = []
        self.on_result = None

    async def connect(self, *, channel_count, sample_rate, model, language, on_result, on_error):
        if self.connect_error:
            raise self.connect_error
        self.connected = True
        self.on_result = on_result

    async def send_audio(self, pcm):
        self.sent.append(pcm)

    async def keepalive(self):
        pass

    async def close(self, *, finalize=True):
        self.closed = True


def channels():
    return (
        RealtimeMuxChannel(0, "p", "p", 0, "primary", "Основной канал", "self"),
        RealtimeMuxChannel(1, "s", "s", 0, "secondary", "Shadow — Не мы", "opponent"),
    )


def make_session(*, ingest=None, provider=None, settings=None, events=None):
    events = events if events is not None else []

    async def broadcast(ev):
        events.append(ev)

    return MultiChannelLiveSession(
        meeting_id=1, owner_user_id=1, ingest=ingest or FakeIngest({}),
        broadcast=broadcast, provider=provider or FakeProvider(),
        channels=channels(), settings=settings or make_settings(),
    )


def res(channel_index, transcript, *, is_final, start=1.0, duration=0.5, speech_final=False):
    return RealtimeProviderResult(
        channel_index=channel_index, channels_count=2, transcript=transcript,
        confidence=0.9, start=start, duration=duration, is_final=is_final,
        speech_final=speech_final, from_finalize=False, words=())


# --- _on_result logic (без запуска задач) ---

async def test_interim_then_final():
    s = make_session()
    s.state.start_server_ms = 0
    s.state.status = "streaming"
    await s._on_result(res(0, "привет", is_final=False))
    assert 0 in s.state.latest_interim_by_channel
    assert len(s.state.final_segments) == 0
    await s._on_result(res(0, "привет", is_final=True))
    assert len(s.state.final_segments) == 1
    assert 0 not in s.state.latest_interim_by_channel       # interim очищен финалом


async def test_interim_empty_clears():
    s = make_session()
    s.state.start_server_ms = 0
    await s._on_result(res(0, "текст", is_final=False))
    assert 0 in s.state.latest_interim_by_channel
    await s._on_result(res(0, "", is_final=False))
    assert 0 not in s.state.latest_interim_by_channel


async def test_final_dedup():
    s = make_session()
    s.state.start_server_ms = 0
    await s._on_result(res(0, "одно и то же", is_final=True))
    await s._on_result(res(0, "одно и то же", is_final=True))   # тот же seg id
    assert len(s.state.final_segments) == 1


async def test_bounded_finals():
    s = make_session(settings=make_settings(multi_channel_live_max_final_segments=3))
    # пересоздать deque с нужным maxlen
    from collections import deque
    s.state.final_segments = deque(maxlen=3)
    s.state.start_server_ms = 0
    for i in range(5):
        await s._on_result(res(0, f"сегмент {i}", is_final=True, start=float(i)))
    assert len(s.state.final_segments) == 3                  # старые вытеснены


async def test_timestamp_mapping():
    s = make_session()
    s.state.start_server_ms = 100000
    await s._on_result(res(0, "x", is_final=True, start=1.0, duration=0.5))
    seg = list(s.state.final_segments)[0]
    assert seg.start_server_ms == 101000 and seg.end_server_ms == 101500


async def test_overlap_preserved_across_channels():
    s = make_session()
    s.state.start_server_ms = 0
    await s._on_result(res(0, "мы говорим", is_final=True, start=1.0, duration=2.0))
    await s._on_result(res(1, "они говорят", is_final=True, start=1.5, duration=2.0))
    assert len(s.state.final_segments) == 2                  # пересечение не объединяется


async def test_clear_results():
    s = make_session()
    s.state.start_server_ms = 0
    await s._on_result(res(0, "a", is_final=True))
    await s._on_result(res(1, "b", is_final=False))
    await s.clear_results()
    assert len(s.state.final_segments) == 0
    assert len(s.state.latest_interim_by_channel) == 0


# --- start/stop/fail ---

def _ingest_with_frames():
    fr = {"p": {i: b"\x01\x02" * 320 for i in range(0, 300)},
          "s": {i: b"\x03\x04" * 320 for i in range(0, 300)}}
    return FakeIngest(fr)


async def test_start_then_stop():
    prov = FakeProvider()
    s = make_session(ingest=_ingest_with_frames(), provider=prov)
    await s.start()
    assert s.state.status == "streaming"
    assert prov.connected is True
    await asyncio.sleep(0.05)
    await s.stop()
    assert s.state.status == "stopped"
    assert prov.closed is True


async def test_start_buffering_failure_no_common_range():
    prov = FakeProvider()
    # нет общего окна → choose_start_index упадёт MUX_BUFFERING
    s = make_session(ingest=FakeIngest({"p": {0: b"\x00" * 640}, "s": {500: b"\x00" * 640}}), provider=prov)
    await s.start()
    assert s.state.status == "failed"
    assert s.state.error_code == "MUX_BUFFERING"
    assert prov.connected is False


async def test_start_provider_connect_failure():
    err = RealtimeMultiChannelProviderError("PROVIDER_CONNECT_FAILED", "no")
    prov = FakeProvider(connect_error=err)
    s = make_session(ingest=_ingest_with_frames(), provider=prov)
    await s.start()
    assert s.state.status == "failed"
    assert s.state.error_code == "PROVIDER_CONNECT_FAILED"


async def test_state_payload_has_no_secrets():
    s = make_session()
    s.state.start_server_ms = 0
    payload = s.state_payload()
    flat = str(payload).lower()
    assert "token" not in flat and "authorization" not in flat
    assert "pcm" not in payload                              # нет ключа pcm


async def test_global_limiter():
    lim = GlobalLiveLimiter()
    assert await lim.try_acquire(2) is True
    assert await lim.try_acquire(2) is True
    assert await lim.try_acquire(2) is False                 # лимит
    await lim.release()
    assert await lim.try_acquire(2) is True
