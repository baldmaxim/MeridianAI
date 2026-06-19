"""Тесты realtime multi-channel mux (Этап 9.6) — interleave/silence/build_chunk/pacing."""

import struct
from types import SimpleNamespace

import pytest

from app.services.multi_source_ingest import (
    MultiSourceIngest, MultiTrackFrameRead, ROLE_PRIMARY, ROLE_SECONDARY,
)
from app.services.realtime_multi_channel_mux import (
    RealtimeMultiChannelMuxer, RealtimeMuxChannel, RealtimeMuxError, RealtimeMuxScheduler,
    interleave_pcm16_frames, pcm16_silence_frame,
)

FRAME_MS = 20
SR = 16000
FRAME_BYTES = 640  # 320 сэмплов * 2


def ch(idx, tid, kind, side=None):
    return RealtimeMuxChannel(channel_index=idx, track_id=tid, connection_id=tid,
                              generation=0, source_kind=kind, label=tid, side=side)


def frame(fill):
    return bytes([fill & 0xFF]) * FRAME_BYTES


class FakeIngest:
    def __init__(self, frames, frame_ms=FRAME_MS):
        self.frames = frames
        self.frame_ms = frame_ms

    def read_tracks_at_index(self, *, track_ids, frame_index):
        out = []
        for tid in track_ids:
            if tid not in self.frames:
                raise KeyError(tid)
            out.append((tid, self.frames[tid].get(frame_index)))
        return MultiTrackFrameRead(frame_index, frame_index * self.frame_ms,
                                   (frame_index + 1) * self.frame_ms, tuple(out))

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


def muxer(ingest, channels, send_chunk_ms=100):
    return RealtimeMultiChannelMuxer(
        ingest=ingest, channels=tuple(channels), sample_rate=SR, frame_ms=FRAME_MS,
        playout_delay_ms=500, send_chunk_ms=send_chunk_ms)


# --- interleave / silence ---

def test_interleave_two_channels_values():
    a = struct.pack("<2h", 100, 101)
    b = struct.pack("<2h", -100, -101)
    out = interleave_pcm16_frames([a, b], expected_mono_bytes=4)
    assert list(struct.unpack("<4h", out)) == [100, -100, 101, -101]


def test_interleave_three_channels_values():
    a = struct.pack("<1h", 1)
    b = struct.pack("<1h", 2)
    c = struct.pack("<1h", 3)
    out = interleave_pcm16_frames([a, b, c], expected_mono_bytes=2)
    assert list(struct.unpack("<3h", out)) == [1, 2, 3]


def test_interleave_malformed_frame_raises():
    with pytest.raises(RealtimeMuxError) as ei:
        interleave_pcm16_frames([b"\x00\x00", b"\x00"], expected_mono_bytes=2)
    assert ei.value.code == "MUX_MALFORMED_FRAME"


def test_silence_frame_size():
    assert len(pcm16_silence_frame(SR, FRAME_MS)) == FRAME_BYTES


# --- build_chunk ---

def test_build_chunk_size_and_order():
    frames = {
        "p": {i: frame(1) for i in range(5000, 5005)},
        "s": {i: frame(2) for i in range(5000, 5005)},
    }
    m = muxer(FakeIngest(frames), [ch(0, "p", ROLE_PRIMARY, "self"), ch(1, "s", ROLE_SECONDARY, "opponent")])
    chunk = m.build_chunk(first_frame_index=5000)
    assert chunk.frame_count == 5 and chunk.channel_count == 2
    assert len(chunk.pcm16_interleaved) == 5 * FRAME_BYTES * 2
    assert chunk.missing_frames_by_channel == (0, 0)
    assert chunk.start_server_ms == 5000 * FRAME_MS
    assert chunk.end_server_ms == 5005 * FRAME_MS


def test_build_chunk_missing_frame_silence_only_that_channel():
    frames = {
        "p": {i: frame(7) for i in range(5000, 5005)},
        "s": {5000: frame(9), 5002: frame(9)},   # пропуски 5001/5003/5004
    }
    m = muxer(FakeIngest(frames), [ch(0, "p", ROLE_PRIMARY), ch(1, "s", ROLE_SECONDARY)])
    chunk = m.build_chunk(first_frame_index=5000)
    # primary без пропусков, secondary 3 пропуска
    assert chunk.missing_frames_by_channel == (0, 3)
    # распакуем первый кадр index 5001: ch0=7-байты, ch1=тишина(0)
    # сэмпл 0 кадра 5001: смещение = 1 кадр * (2 канала * 320 сэмплов) = 640 int16
    ints = struct.unpack("<%dh" % (5 * 320 * 2), chunk.pcm16_interleaved)
    base = 320 * 2  # начало кадра index 5001 (в сэмплах int16, interleaved)
    # ch0 sample0 кадра 5001 != 0 (есть аудио), ch1 sample0 == 0 (тишина)
    ch0_s0 = ints[base + 0]
    ch1_s0 = ints[base + 1]
    assert ch0_s0 != 0 and ch1_s0 == 0


def test_build_chunk_does_not_mutate_real_ingest():
    s = SimpleNamespace(multi_source_ingest_enabled=True, multi_source_ingest_frame_ms=FRAME_MS,
                        multi_source_ingest_window_seconds=8, multi_source_ingest_max_tracks=6)
    ing = MultiSourceIngest(s)
    ing.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=b"\x01\x02" * (320 * 5))
    ing.ingest("x", ROLE_SECONDARY, server_ts_ms=100000, arrival_ms=100000,
               pcm=b"\x03\x04" * (320 * 5), seq=1)
    t = ing.tracks["p"]
    before = (t.frames_count, len(t.frames), list(t.order))
    m = muxer(ing, [ch(0, "p", ROLE_PRIMARY), ch(1, "x", ROLE_SECONDARY)])
    m.build_chunk(first_frame_index=5000)
    after = (t.frames_count, len(t.frames), list(t.order))
    assert before == after


# --- choose_start_index ---

def test_choose_start_index_within_common_with_prebuffer():
    frames = {"p": {i: frame(1) for i in range(1000, 1200)},
              "s": {i: frame(2) for i in range(1000, 1200)}}
    m = muxer(FakeIngest(frames), [ch(0, "p", ROLE_PRIMARY), ch(1, "s", ROLE_SECONDARY)])
    # now далеко в будущем → старт ограничен max_start = hi - prebuffer + 1
    start = m.choose_start_index(now_server_ms=10_000_000, min_prebuffer_ms=1000)
    prebuffer_frames = 1000 // FRAME_MS  # 50
    assert start == 1199 - prebuffer_frames + 1   # 1150
    assert 1000 <= start <= 1199


def test_choose_start_index_insufficient_prebuffer():
    frames = {"p": {i: frame(1) for i in range(1000, 1010)},
              "s": {i: frame(2) for i in range(1000, 1010)}}   # всего 10 кадров < 50
    m = muxer(FakeIngest(frames), [ch(0, "p", ROLE_PRIMARY), ch(1, "s", ROLE_SECONDARY)])
    with pytest.raises(RealtimeMuxError) as ei:
        m.choose_start_index(now_server_ms=10_000_000, min_prebuffer_ms=1000)
    assert ei.value.code == "MUX_BUFFERING"


def test_choose_start_index_no_common_range():
    frames = {"p": {i: frame(1) for i in range(1000, 1100)},
              "s": {i: frame(2) for i in range(2000, 2100)}}   # не пересекаются
    m = muxer(FakeIngest(frames), [ch(0, "p", ROLE_PRIMARY), ch(1, "s", ROLE_SECONDARY)])
    with pytest.raises(RealtimeMuxError) as ei:
        m.choose_start_index(now_server_ms=10_000_000, min_prebuffer_ms=1000)
    assert ei.value.code == "MUX_BUFFERING"


# --- silence ratios ---

def test_channel_silence_ratios():
    frames = {"p": {i: frame(1) for i in range(0, 5)}, "s": {}}   # secondary весь пустой
    m = muxer(FakeIngest(frames), [ch(0, "p", ROLE_PRIMARY), ch(1, "s", ROLE_SECONDARY)])
    m.build_chunk(first_frame_index=0)
    ratios = m.channel_silence_ratios()
    assert ratios[0] == 0.0 and ratios[1] == 1.0


def test_consecutive_silence_ms_windowed():
    # primary всегда есть; secondary молчит → хвостовая тишина растёт; затем секунда аудио → сброс
    frames = {"p": {i: frame(1) for i in range(0, 20)},
              "s": {i: frame(2) for i in range(0, 5)}}   # s есть только 0..4, дальше тишина
    m = muxer(FakeIngest(frames), [ch(0, "p", ROLE_PRIMARY), ch(1, "s", ROLE_SECONDARY)])
    m.build_chunk(first_frame_index=0)    # 0..4: s есть → consec=0
    m.build_chunk(first_frame_index=5)    # 5..9: s нет → 5 кадров тишины
    sm = m.consecutive_silence_ms()
    assert sm[0] == 0                      # primary не молчит
    assert sm[1] == 5 * FRAME_MS           # secondary: 5 кадров * 20мс = 100мс
    # вернулось аудио secondary → сброс
    frames["s"][10] = frame(2); frames["s"][11] = frame(2)
    frames["s"][12] = frame(2); frames["s"][13] = frame(2); frames["s"][14] = frame(2)
    m.build_chunk(first_frame_index=10)
    assert m.consecutive_silence_ms()[1] == 0


# --- scheduler ---

def test_scheduler_monotonic_indices_no_duplicates():
    frames = {"p": {i: frame(1) for i in range(0, 100)}, "s": {i: frame(2) for i in range(0, 100)}}
    m = muxer(FakeIngest(frames), [ch(0, "p", ROLE_PRIMARY), ch(1, "s", ROLE_SECONDARY)])
    sched = RealtimeMuxScheduler(muxer=m, start_frame_index=10, send_chunk_ms=100)
    idxs = [sched.first_index_for(n) for n in range(4)]
    assert idxs == [10, 15, 20, 25]      # frames_per_chunk=5, монотонно, без дублей


def test_scheduler_pacing_overrun_detected():
    frames = {"p": {i: frame(1) for i in range(0, 100)}, "s": {i: frame(2) for i in range(0, 100)}}
    m = muxer(FakeIngest(frames), [ch(0, "p", ROLE_PRIMARY), ch(1, "s", ROLE_SECONDARY)])
    sched = RealtimeMuxScheduler(muxer=m, start_frame_index=0, send_chunk_ms=100, max_pacing_lag_ms=10)
    sched.begin()
    # симулируем отставание: сдвигаем start_monotonic далеко в прошлое
    sched._start_monotonic -= 100.0
    with pytest.raises(RealtimeMuxError) as ei:
        sched.next_chunk_blocking_delay()
    assert ei.value.code == "MUX_PACING_OVERRUN"
