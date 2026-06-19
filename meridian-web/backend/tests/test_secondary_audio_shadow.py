"""Тесты secondary audio shadow (Этап 9.2) — pure ring buffer + диагностика."""

from types import SimpleNamespace

from app.services.secondary_audio_shadow import (
    SecondaryAudioShadow,
    chunk_duration_ms,
)

CID = "conn-1"


def make_settings(**over):
    base = dict(
        secondary_audio_shadow_enabled=True,
        secondary_audio_shadow_max_devices=2,
        secondary_audio_shadow_max_buffer_seconds=1,
        secondary_audio_shadow_target_sample_rate=16000,
        secondary_audio_shadow_max_chunk_ms=250,
        secondary_audio_shadow_max_chunk_bytes=32000,
        secondary_audio_shadow_accept_pcm16=True,
        secondary_audio_shadow_accept_float32=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


def mk(**over):
    return SecondaryAudioShadow(make_settings(**over))


def _enable(s, cid=CID, sr=16000, ch=1, codec="pcm16", side="opponent"):
    s.register_track(cid, user_id=1)
    return s.enable_track(cid, sample_rate=sr, channels=ch, codec=codec, side_hint=side)


# --- duration ---

def test_chunk_duration_pcm16_100ms():
    # 1600 сэмплов * 2 байта = 3200 байт @16k = 100 мс
    assert chunk_duration_ms(3200, 16000, 1, "pcm16") == 100


def test_chunk_duration_float32():
    # 1600 сэмплов * 4 байта = 6400 байт @16k = 100 мс
    assert chunk_duration_ms(6400, 16000, 1, "float32") == 100


# --- enable gating ---

def test_enable_ok():
    s = mk()
    ok, reason = _enable(s)
    assert ok and reason is None
    assert s.tracks[CID].enabled is True


def test_enable_codec_rejected():
    s = mk()
    s.register_track(CID, 1)
    ok, reason = s.enable_track(CID, sample_rate=16000, channels=1, codec="opus")
    assert not ok and reason == "codec_rejected"


def test_enable_float32_rejected_when_disabled():
    s = mk()  # accept_float32 = False
    s.register_track(CID, 1)
    ok, reason = s.enable_track(CID, sample_rate=16000, channels=1, codec="float32")
    assert not ok and reason == "codec_rejected"


def test_enable_max_devices():
    s = mk(secondary_audio_shadow_max_devices=1)
    _enable(s, "a")
    s.register_track("b", 2)
    ok, reason = s.enable_track("b", sample_rate=16000, channels=1, codec="pcm16")
    assert not ok and reason == "max_devices"


def test_enable_disabled_in_config():
    s = mk(secondary_audio_shadow_enabled=False)
    s.register_track(CID, 1)
    ok, reason = s.enable_track(CID, sample_rate=16000, channels=1, codec="pcm16")
    assert not ok and reason == "shadow_disabled"


# --- ingest ---

def test_add_chunk_before_enable_rejected():
    s = mk()
    s.register_track(CID, 1)
    ok, reason = s.add_chunk(CID, seq=1, client_ts_ms=1000, server_ts_ms=1000,
                             payload_bytes=3200, payload=b"\x00" * 3200)
    assert not ok and reason == "not_enabled"


def test_add_chunk_accepted_updates_stats():
    s = mk()
    _enable(s)
    ok, reason = s.add_chunk(CID, seq=1, client_ts_ms=1000, server_ts_ms=1000,
                             payload_bytes=3200, payload=b"\x00" * 3200)
    assert ok and reason is None
    t = s.tracks[CID]
    assert t.chunks_count == 1
    assert t.bytes_count == 3200
    assert t.last_duration_ms == 100
    assert t.estimated_buffer_ms == 100
    assert t.status == "recording"


def test_add_chunk_too_large():
    s = mk(secondary_audio_shadow_max_chunk_bytes=1000)
    _enable(s)
    ok, reason = s.add_chunk(CID, seq=1, client_ts_ms=0, server_ts_ms=0,
                             payload_bytes=3200, payload=b"\x00" * 3200)
    assert not ok and reason == "chunk_too_large"
    assert s.tracks[CID].dropped_chunks == 1


def test_add_chunk_too_long():
    s = mk(secondary_audio_shadow_max_chunk_ms=50)
    _enable(s)
    ok, reason = s.add_chunk(CID, seq=1, client_ts_ms=0, server_ts_ms=0,
                             payload_bytes=3200, payload=b"\x00" * 3200)  # 100мс > 50мс
    assert not ok and reason == "chunk_too_long"


def test_add_chunk_out_of_order():
    s = mk()
    _enable(s)
    s.add_chunk(CID, seq=5, client_ts_ms=0, server_ts_ms=0,
                payload_bytes=3200, payload=b"\x00" * 3200)
    ok, reason = s.add_chunk(CID, seq=3, client_ts_ms=0, server_ts_ms=0,
                             payload_bytes=3200, payload=b"\x00" * 3200)
    assert not ok and reason == "out_of_order"


def test_gap_detection_by_seq():
    s = mk()
    _enable(s)
    s.add_chunk(CID, seq=1, client_ts_ms=0, server_ts_ms=0,
                payload_bytes=3200, payload=b"\x00" * 3200)
    s.add_chunk(CID, seq=4, client_ts_ms=300, server_ts_ms=300,
                payload_bytes=3200, payload=b"\x00" * 3200)  # пропуск 2,3
    assert s.tracks[CID].gaps_count == 1


def test_buffer_trim_by_duration():
    s = mk(secondary_audio_shadow_max_buffer_seconds=1)  # 1000 мс
    _enable(s)
    for i in range(1, 16):  # 15 чанков по 100мс
        s.add_chunk(CID, seq=i, client_ts_ms=i * 100, server_ts_ms=i * 100,
                    payload_bytes=3200, payload=b"\x00" * 3200)
    t = s.tracks[CID]
    assert t.chunks_count == 15           # cumulative — растёт
    assert t.estimated_buffer_ms <= 1000  # ring buffer ограничен


def test_diag_stale_via_now_ms():
    s = mk()
    _enable(s)
    s.add_chunk(CID, seq=1, client_ts_ms=0, server_ts_ms=1000,
                payload_bytes=3200, payload=b"\x00" * 3200)
    diag = s.track_diag(CID, now_ms=1000 + 10_000)  # давно не было кадров
    assert diag["status"] == "stale"
    assert diag["last_packet_age_ms"] == 10_000


def test_add_chunk_too_short_rejected():
    # крошечный payload → duration округляется в 0 мс → отбрасываем (иначе ring buffer растёт)
    s = mk()
    _enable(s)
    ok, reason = s.add_chunk(CID, seq=1, client_ts_ms=0, server_ts_ms=0,
                             payload_bytes=2, payload=b"\x00\x00")
    assert not ok and reason == "chunk_too_short"
    assert s.tracks[CID].dropped_chunks == 1
    assert len(s._buffers[CID]) == 0


def test_buffer_hard_chunk_cap():
    # 1-мс чанки (32 байта) не достигают duration-лимита буфера, но count-cap держит размер
    s = mk(secondary_audio_shadow_max_buffer_seconds=1)  # max_chunks = ceil(1000/20) = 50
    _enable(s)
    for i in range(1, 61):  # 60 чанков по ~1мс
        s.add_chunk(CID, seq=i, client_ts_ms=i, server_ts_ms=i,
                    payload_bytes=32, payload=b"\x00" * 32)
    assert s.max_chunks == 50
    assert len(s._buffers[CID]) <= s.max_chunks


def test_reenable_resets_sequence():
    # disable → enable на ТОМ ЖЕ соединении: клиент рестартует seq с 1 — должно приниматься
    s = mk()
    _enable(s)
    s.add_chunk(CID, seq=5, client_ts_ms=500, server_ts_ms=500,
                payload_bytes=3200, payload=b"\x00" * 3200)
    s.disable_track(CID)
    assert s.tracks[CID].last_seq is None
    ok, reason = s.enable_track(CID, sample_rate=16000, channels=1, codec="pcm16")
    assert ok
    ok2, _ = s.add_chunk(CID, seq=1, client_ts_ms=0, server_ts_ms=0,
                         payload_bytes=3200, payload=b"\x00" * 3200)
    assert ok2  # seq=1 после рестарта не считается out_of_order


def test_disable_clears_buffer():
    s = mk()
    _enable(s)
    s.add_chunk(CID, seq=1, client_ts_ms=0, server_ts_ms=0,
                payload_bytes=3200, payload=b"\x00" * 3200)
    s.disable_track(CID)
    t = s.tracks[CID]
    assert t.enabled is False
    assert t.estimated_buffer_ms == 0
    assert s.track_diag(CID, now_ms=0)["status"] == "idle"
