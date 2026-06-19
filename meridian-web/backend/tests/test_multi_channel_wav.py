"""Тесты multi-channel WAV export (Этап 9.4) — pure-сборка + snapshot + API."""

import struct
from types import SimpleNamespace

import pytest

from app.services.multi_channel_wav import (
    MultiChannelExportError,
    build_channel_pcm16,
    build_export_plan,
    build_multi_channel_wav,
    build_pcm16_wav_header,
    default_channel_order,
    export_plan_to_manifest,
    interleave_pcm16_channels,
    resolve_export_window,
)
from app.services.multi_source_ingest import (
    AudioTrackFrameSnapshot,
    MultiSourceWindowSnapshot,
    MultiSourceIngest,
    ROLE_PRIMARY,
    ROLE_SECONDARY,
)
from datetime import datetime, timezone

SR = 16000
FRAME_MS = 20
SPF = SR * FRAME_MS // 1000          # 320
FRAME_BYTES = SPF * 2                 # 640


def frame(fill: int) -> bytes:
    return bytes([fill & 0xFF]) * FRAME_BYTES


def mk_track(track_id, role, side, frames: dict, *, sr=SR, status="ready", diag=None):
    return AudioTrackFrameSnapshot(
        track_id=track_id, connection_id=track_id, generation=0, source_kind=role,
        side_hint=side, status=status, sample_rate=sr, frame_ms=FRAME_MS,
        first_index=(min(frames) if frames else None),
        last_index=(max(frames) if frames else None),
        frames=frames, diagnostics=(diag or {}),
    )


def mk_snapshot(tracks, start, end):
    return MultiSourceWindowSnapshot(
        created_server_ms=0, sample_rate=SR, frame_ms=FRAME_MS,
        start_index=start, end_index=end, tracks=tuple(tracks),
    )


# ============================ WAV header ============================

@pytest.mark.parametrize("channels", [1, 2, 4])
def test_wav_header_sizes(channels):
    spc = 320
    h = build_pcm16_wav_header(sample_rate=SR, channels=channels, samples_per_channel=spc)
    assert len(h) == 44
    assert h[:4] == b"RIFF" and h[8:12] == b"WAVE" and h[36:40] == b"data"
    block_align = channels * 2
    data_bytes = spc * block_align
    assert struct.unpack("<I", h[4:8])[0] == 36 + data_bytes      # ChunkSize
    assert struct.unpack("<I", h[16:20])[0] == 16                  # Subchunk1Size
    assert struct.unpack("<H", h[20:22])[0] == 1                   # PCM
    assert struct.unpack("<H", h[22:24])[0] == channels
    assert struct.unpack("<I", h[24:28])[0] == SR
    assert struct.unpack("<I", h[28:32])[0] == SR * block_align    # ByteRate
    assert struct.unpack("<H", h[32:34])[0] == block_align         # BlockAlign
    assert struct.unpack("<H", h[34:36])[0] == 16                  # bits
    assert struct.unpack("<I", h[40:44])[0] == data_bytes


# ============================ interleave ============================

def test_interleave_two_channels_values():
    a = struct.pack("<4h", 1000, 1001, 1002, 1003)
    b = struct.pack("<4h", -1000, -1001, -1002, -1003)
    out = interleave_pcm16_channels([a, b])
    assert list(struct.unpack("<8h", out)) == [1000, -1000, 1001, -1001, 1002, -1002, 1003, -1003]


def test_interleave_three_channels_values():
    a = struct.pack("<2h", 10, 11)
    b = struct.pack("<2h", 20, 21)
    c = struct.pack("<2h", 30, 31)
    out = interleave_pcm16_channels([a, b, c])
    assert list(struct.unpack("<6h", out)) == [10, 20, 30, 11, 21, 31]


def test_interleave_single_channel_passthrough():
    a = struct.pack("<3h", 5, 6, 7)
    assert interleave_pcm16_channels([a]) == a


def test_interleave_length_mismatch_rejected():
    with pytest.raises(MultiChannelExportError):
        interleave_pcm16_channels([b"\x00\x00", b"\x00\x00\x00\x00"])


# ============================ silence fill ============================

def test_silence_fill_positions_and_equal_length():
    # track A полный 0..2; track B пропускает середину (index 1)
    a = {0: frame(1), 1: frame(2), 2: frame(3)}
    b = {0: frame(9), 2: frame(9)}
    ta = mk_track("a", ROLE_PRIMARY, None, a)
    tb = mk_track("b", ROLE_SECONDARY, "opponent", b)
    ca = build_channel_pcm16(track=ta, start_index=0, end_index=3, sample_rate=SR, frame_ms=FRAME_MS, offset_ms=0)
    cb = build_channel_pcm16(track=tb, start_index=0, end_index=3, sample_rate=SR, frame_ms=FRAME_MS, offset_ms=0)
    assert len(ca) == len(cb) == 3 * FRAME_BYTES
    # B середина — тишина, A — нет
    assert cb[FRAME_BYTES:2 * FRAME_BYTES] == b"\x00" * FRAME_BYTES
    assert ca[FRAME_BYTES:2 * FRAME_BYTES] == frame(2)


def test_silence_missing_start_and_end():
    b = {1: frame(7)}  # отсутствуют 0 и 2
    tb = mk_track("b", ROLE_SECONDARY, "self", b)
    cb = build_channel_pcm16(track=tb, start_index=0, end_index=3, sample_rate=SR, frame_ms=FRAME_MS, offset_ms=0)
    assert cb[:FRAME_BYTES] == b"\x00" * FRAME_BYTES
    assert cb[2 * FRAME_BYTES:] == b"\x00" * FRAME_BYTES
    assert cb[FRAME_BYTES:2 * FRAME_BYTES] == frame(7)


def test_spf_matches_ingest_round_for_non_16k():
    from app.services.multi_channel_wav import samples_per_frame
    # round(), как в ingest: 44100*15/1000=661.5 → 662 (не 661)
    assert samples_per_frame(44100, 15) == 662
    assert samples_per_frame(22050, 30) == 662
    assert samples_per_frame(16000, 20) == 320          # default неизменён


def test_non_16k_frames_not_treated_as_corrupt():
    # кадр 44100/15мс имеет размер round(661.5)*2 = 1324 байта; не должен стать тишиной
    fb = 662 * 2
    t = AudioTrackFrameSnapshot(
        track_id="x", connection_id="x", generation=0, source_kind=ROLE_SECONDARY,
        side_hint="opponent", status="ready", sample_rate=44100, frame_ms=15,
        first_index=0, last_index=0, frames={0: bytes([7]) * fb}, diagnostics={},
    )
    c = build_channel_pcm16(track=t, start_index=0, end_index=1,
                            sample_rate=44100, frame_ms=15, offset_ms=0)
    assert c == bytes([7]) * fb                          # реальный кадр, не тишина


def test_corrupt_frame_becomes_silence():
    t = mk_track("a", ROLE_PRIMARY, None, {0: b"\x01\x02"})  # wrong size
    c = build_channel_pcm16(track=t, start_index=0, end_index=1, sample_rate=SR, frame_ms=FRAME_MS, offset_ms=0)
    assert c == b"\x00" * FRAME_BYTES


# ============================ offsets ============================

def test_offset_positive_shifts_later_same_length():
    frames = {i: frame(5) for i in range(5)}
    t = mk_track("a", ROLE_PRIMARY, None, frames)
    base_len = 5 * FRAME_BYTES
    # +20мс = +1 frame (320 сэмплов = 640 байт)
    c = build_channel_pcm16(track=t, start_index=0, end_index=5, sample_rate=SR, frame_ms=FRAME_MS, offset_ms=20)
    assert len(c) == base_len
    assert c[:FRAME_BYTES] == b"\x00" * FRAME_BYTES          # тишина спереди
    assert c[FRAME_BYTES:] == frame(5) * 4                    # сдвиг, хвост обрезан


def test_offset_negative_shifts_earlier_same_length():
    frames = {i: frame(5) for i in range(5)}
    t = mk_track("a", ROLE_PRIMARY, None, frames)
    c = build_channel_pcm16(track=t, start_index=0, end_index=5, sample_rate=SR, frame_ms=FRAME_MS, offset_ms=-20)
    assert len(c) == 5 * FRAME_BYTES
    assert c[-FRAME_BYTES:] == b"\x00" * FRAME_BYTES          # тишина в хвосте


def test_offset_sample_level_5ms():
    # 5мс @16к = 80 сэмплов = 160 байт (sub-frame!)
    frames = {i: frame(5) for i in range(3)}
    t = mk_track("a", ROLE_PRIMARY, None, frames)
    c = build_channel_pcm16(track=t, start_index=0, end_index=3, sample_rate=SR, frame_ms=FRAME_MS, offset_ms=5)
    assert len(c) == 3 * FRAME_BYTES
    assert c[:160] == b"\x00" * 160       # ровно 80 сэмплов тишины
    assert c[160:160 + 8] == frame(5)[:8]


def test_offset_over_limit_rejected_in_plan():
    snap = mk_snapshot([mk_track("a", ROLE_PRIMARY, None, {0: frame(1)})], 0, 1)
    with pytest.raises(MultiChannelExportError) as ei:
        build_export_plan(snapshot=snap, ordered_track_ids=["a"], offsets_ms={"a": 99999},
                          max_channels=4, max_seconds=120, max_bytes=33554432, max_offset_ms=2000)
    assert ei.value.code == "INVALID_OFFSET"


def test_offset_bool_rejected_in_plan():
    snap = mk_snapshot([mk_track("a", ROLE_PRIMARY, None, {0: frame(1)})], 0, 1)
    with pytest.raises(MultiChannelExportError) as ei:
        build_export_plan(snapshot=snap, ordered_track_ids=["a"], offsets_ms={"a": True},
                          max_channels=4, max_seconds=120, max_bytes=33554432, max_offset_ms=2000)
    assert ei.value.code == "INVALID_OFFSET"


# ============================ windows ============================

def _tinfo(track_id, first, last):
    return {"track_id": track_id, "first_index": first, "last_index": last}


def test_window_common_intersection():
    tracks = [_tinfo("a", 100, 110), _tinfo("b", 105, 120)]
    start, end = resolve_export_window(tracks=tracks, mode="common", frame_ms=FRAME_MS,
                                       default_seconds=30, max_seconds=120)
    assert (start, end) == (105, 111)   # max first, min last + 1


def test_window_common_no_intersection():
    tracks = [_tinfo("a", 100, 104), _tinfo("b", 200, 210)]
    with pytest.raises(MultiChannelExportError) as ei:
        resolve_export_window(tracks=tracks, mode="common", frame_ms=FRAME_MS,
                              default_seconds=30, max_seconds=120)
    assert ei.value.code == "NO_COMMON_WINDOW"


def test_window_last_n_seconds_and_late_start_silence():
    # b начинается позже; last 1с (=50 кадров) от конца, clamp к global_min
    tracks = [_tinfo("a", 1000, 1100), _tinfo("b", 1080, 1100)]
    start, end = resolve_export_window(tracks=tracks, mode="last", frame_ms=FRAME_MS,
                                       default_seconds=30, max_seconds=120, duration_seconds=1)
    assert end == 1101
    assert start == 1101 - 50           # 1051; b (1080..) до своего первого кадра — тишина
    assert start < 1080


def test_window_explicit():
    tracks = [_tinfo("a", 4000, 6000)]
    start, end = resolve_export_window(tracks=tracks, mode="explicit", frame_ms=FRAME_MS,
                                       default_seconds=30, max_seconds=120,
                                       start_server_ms=100000, end_server_ms=100400)
    assert start == 100000 // FRAME_MS == 5000
    assert end == 100400 // FRAME_MS == 5020


def test_window_explicit_huge_range_rejected_before_snapshot():
    # регресс DoS: огромный explicit-интервал отбивается DURATION_LIMIT, без прокрутки range()
    tracks = [_tinfo("a", 5000, 5005)]
    with pytest.raises(MultiChannelExportError) as ei:
        resolve_export_window(tracks=tracks, mode="explicit", frame_ms=FRAME_MS,
                              default_seconds=30, max_seconds=120,
                              start_server_ms=0, end_server_ms=10**15)
    assert ei.value.code == "DURATION_LIMIT"


def test_window_explicit_no_overlap():
    tracks = [_tinfo("a", 0, 10)]
    with pytest.raises(MultiChannelExportError) as ei:
        resolve_export_window(tracks=tracks, mode="explicit", frame_ms=FRAME_MS,
                              default_seconds=30, max_seconds=120,
                              start_server_ms=100000, end_server_ms=100400)
    assert ei.value.code == "NO_AUDIO_DATA"


def test_window_duration_limit_in_plan():
    frames = {i: frame(1) for i in range(0, 100)}
    snap = mk_snapshot([mk_track("a", ROLE_PRIMARY, None, frames)], 0, 100)  # 100*20=2000мс
    with pytest.raises(MultiChannelExportError) as ei:
        build_export_plan(snapshot=snap, ordered_track_ids=["a"], offsets_ms={},
                          max_channels=4, max_seconds=1, max_bytes=33554432, max_offset_ms=2000)
    assert ei.value.code == "DURATION_LIMIT"


def test_byte_limit_in_plan():
    frames = {i: frame(1) for i in range(0, 50)}
    snap = mk_snapshot([mk_track("a", ROLE_PRIMARY, None, frames)], 0, 50)
    with pytest.raises(MultiChannelExportError) as ei:
        build_export_plan(snapshot=snap, ordered_track_ids=["a"], offsets_ms={},
                          max_channels=4, max_seconds=120, max_bytes=100, max_offset_ms=2000)
    assert ei.value.code == "BYTE_LIMIT"


# ============================ channel order / plan ============================

def test_default_channel_order_deterministic():
    tracks = [
        {"track_id": "z_sec_opp", "source_kind": "secondary", "side_hint": "opponent", "is_active": False},
        {"track_id": "a_sec_self", "source_kind": "secondary", "side_hint": "self", "is_active": False},
        {"track_id": "p_active", "source_kind": "primary", "side_hint": None, "is_active": True},
        {"track_id": "p_other", "source_kind": "primary", "side_hint": None, "is_active": False},
        {"track_id": "m_sec_none", "source_kind": "secondary", "side_hint": None, "is_active": False},
    ]
    order = default_channel_order(tracks)
    assert order == ["p_active", "p_other", "a_sec_self", "z_sec_opp", "m_sec_none"]


def test_request_channel_order_preserved_in_plan():
    snap = mk_snapshot([
        mk_track("a", ROLE_PRIMARY, None, {0: frame(1)}),
        mk_track("b", ROLE_SECONDARY, "opponent", {0: frame(2)}),
    ], 0, 1)
    plan = build_export_plan(snapshot=snap, ordered_track_ids=["b", "a"], offsets_ms={},
                             max_channels=4, max_seconds=120, max_bytes=33554432, max_offset_ms=2000)
    assert [c.track_id for c in plan.channels] == ["b", "a"]
    assert plan.channels[0].channel_index == 0 and plan.channels[0].track_id == "b"


def test_too_many_channels():
    tracks = [mk_track(str(i), ROLE_SECONDARY, None, {0: frame(1)}) for i in range(5)]
    snap = mk_snapshot(tracks, 0, 1)
    with pytest.raises(MultiChannelExportError) as ei:
        build_export_plan(snapshot=snap, ordered_track_ids=[str(i) for i in range(5)],
                          offsets_ms={}, max_channels=4, max_seconds=120,
                          max_bytes=33554432, max_offset_ms=2000)
    assert ei.value.code == "TOO_MANY_CHANNELS"


def test_no_audio_data_when_window_empty_of_frames():
    snap = mk_snapshot([mk_track("a", ROLE_PRIMARY, None, {})], 0, 5)
    with pytest.raises(MultiChannelExportError) as ei:
        build_export_plan(snapshot=snap, ordered_track_ids=["a"], offsets_ms={},
                          max_channels=4, max_seconds=120, max_bytes=33554432, max_offset_ms=2000)
    assert ei.value.code == "NO_AUDIO_DATA"


def test_build_wav_end_to_end_size_and_riff():
    a = {i: frame(1) for i in range(5)}
    b = {i: frame(2) for i in range(5)}
    snap = mk_snapshot([
        mk_track("a", ROLE_PRIMARY, None, a),
        mk_track("b", ROLE_SECONDARY, "opponent", b),
    ], 0, 5)
    plan = build_export_plan(snapshot=snap, ordered_track_ids=["a", "b"], offsets_ms={},
                             max_channels=4, max_seconds=120, max_bytes=33554432, max_offset_ms=2000)
    wav = build_multi_channel_wav(snapshot=snap, plan=plan)
    assert wav[:4] == b"RIFF"
    assert len(wav) == plan.wav_bytes == 44 + 5 * SPF * 2 * 2
    assert plan.channel_count == 2
    man = export_plan_to_manifest(plan, meeting_id=7, created_at=datetime.now(timezone.utc))
    assert man["channels_count"] == 2 and len(man["channels"]) == 2
    assert "pcm" not in str(man).lower() or man["format"] == "pcm_s16le_wav"  # no raw pcm payload


# ============================ snapshot immutability ============================

def _ingest_settings():
    return SimpleNamespace(multi_source_ingest_enabled=True, multi_source_ingest_frame_ms=FRAME_MS,
                           multi_source_ingest_window_seconds=8, multi_source_ingest_max_tracks=6)


def test_snapshot_does_not_mutate_ingest():
    ing = MultiSourceIngest(_ingest_settings())
    ing.ingest("a", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=b"\x01\x02" * (SPF * 5))
    t = ing.tracks["a"]
    frames_before = dict(t.frames)
    fc_before, order_before = t.frames_count, list(t.order)

    snap = ing.snapshot_window(track_ids=["a"], start_index=5000, end_index=5003, now_ms=100000)
    # snapshot содержит только окно
    assert set(snap.tracks[0].frames.keys()) <= {5000, 5001, 5002}
    # ingest не изменился
    assert t.frames.keys() == frames_before.keys()
    assert t.frames_count == fc_before and list(t.order) == order_before

    # дальнейший ingest не меняет уже снятый snapshot
    snap_keys = set(snap.tracks[0].frames.keys())
    ing.ingest("a", ROLE_PRIMARY, server_ts_ms=100100, arrival_ms=100100, pcm=b"\x03\x04" * (SPF * 5))
    assert set(snap.tracks[0].frames.keys()) == snap_keys


def test_snapshot_unknown_track_raises():
    ing = MultiSourceIngest(_ingest_settings())
    ing.ingest("a", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=b"\x01\x02" * SPF)
    with pytest.raises(KeyError):
        ing.snapshot_window(track_ids=["nope"], start_index=5000, end_index=5001, now_ms=100000)


def test_list_exportable_excludes_empty_unless_included():
    ing = MultiSourceIngest(_ingest_settings())
    ing.register_track("empty", ROLE_SECONDARY)
    ing.ingest("a", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=b"\x01\x02" * SPF)
    ids = {t["track_id"] for t in ing.list_exportable_tracks(now_ms=100000)}
    assert ids == {"a"}
    ids2 = {t["track_id"] for t in ing.list_exportable_tracks(include_stopped=True, now_ms=100000)}
    assert "empty" in ids2


# ============================ API (dependency overrides + fake room, без БД) ============================

@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.dependencies import get_current_user
    from app.database import get_db
    from app.services import meeting_room as mrmod

    state = SimpleNamespace(meeting_exists=True)

    class FakeUser:
        id = 1
        role = "admin"
        is_active = True

    class FakeDB:
        async def get(self, model, pk):
            return object() if state.meeting_exists else None

    fake_db = FakeDB()

    async def _db():
        yield fake_db

    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = _db

    ing = MultiSourceIngest(_ingest_settings())
    ing.ingest("a", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=b"\x01\x02" * (SPF * 5))
    ing.ingest("b", ROLE_SECONDARY, server_ts_ms=100000, arrival_ms=100000,
               pcm=b"\x03\x04" * (SPF * 5), seq=1, side_hint="opponent")
    state.room = SimpleNamespace(ingest=ing, connections={}, active_audio_source="a")
    monkeypatch.setattr(mrmod.room_registry, "get_room", lambda mid: state.room)

    state.client = TestClient(app)
    try:
        yield state
    finally:
        app.dependency_overrides.clear()


def test_api_export_plan_200(api):
    r = api.client.post("/api/meetings/1/multi-source/export-plan",
                        json={"track_ids": ["a", "b"], "window_mode": "last"})
    assert r.status_code == 200
    body = r.json()
    assert body["channels_count"] == 2
    assert [c["track_id"] for c in body["channels"]] == ["a", "b"]
    assert "pcm" not in body and body["format"] == "pcm_s16le_wav"


def test_api_wav_200_riff_and_headers(api):
    r = api.client.post("/api/meetings/1/multi-source/wav",
                        json={"track_ids": ["a", "b"], "window_mode": "last"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"
    assert int(r.headers["content-length"]) == len(r.content)
    assert r.headers["x-meridian-channels"] == "2"


def test_api_404_meeting_not_found(api):
    api.meeting_exists = False
    r = api.client.post("/api/meetings/1/multi-source/wav",
                        json={"track_ids": ["a"], "window_mode": "last"})
    assert r.status_code == 404


def test_api_409_no_room(api):
    api.room = None
    r = api.client.post("/api/meetings/1/multi-source/wav",
                        json={"track_ids": ["a"], "window_mode": "last"})
    assert r.status_code == 409


def test_api_503_disabled(api, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "multi_channel_export_enabled", False)
    r = api.client.post("/api/meetings/1/multi-source/wav",
                        json={"track_ids": ["a"], "window_mode": "last"})
    assert r.status_code == 503


def test_api_422_unknown_track(api):
    r = api.client.post("/api/meetings/1/multi-source/wav",
                        json={"track_ids": ["nope"], "window_mode": "last"})
    assert r.status_code == 422


def test_api_does_not_mutate_ingest(api):
    t = api.room.ingest.tracks["a"]
    before = (t.frames_count, len(t.frames), list(t.order))
    api.client.post("/api/meetings/1/multi-source/wav",
                    json={"track_ids": ["a", "b"], "window_mode": "last"})
    after = (t.frames_count, len(t.frames), list(t.order))
    assert before == after
