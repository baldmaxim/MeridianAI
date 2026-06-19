"""Тесты multi-source ingest (Этап 9.3) — canonical grid, окно, метрики, выравнивание."""

from types import SimpleNamespace

from app.services.multi_source_ingest import (
    MultiSourceIngest,
    ROLE_PRIMARY,
    ROLE_SECONDARY,
)


def make_settings(**over):
    base = dict(
        multi_source_ingest_enabled=True,
        multi_source_ingest_frame_ms=20,          # 20мс @16к = 320 сэмплов = 640 байт
        multi_source_ingest_window_seconds=1,     # max_frames = 1000//20 = 50
        multi_source_ingest_max_tracks=6,
    )
    base.update(over)
    return SimpleNamespace(**base)


def mk(**over):
    return MultiSourceIngest(make_settings(**over))


def pcm(n_bytes: int) -> bytes:
    return bytes(i % 256 for i in range(n_bytes))


# --- canonical framing ---

def test_frame_geometry():
    s = mk()
    assert s.frame_ms == 20
    assert s.max_frames == 50
    t = s.register_track("p", ROLE_PRIMARY)
    assert t.frame_bytes == 640      # 320 сэмплов * 2 байта
    assert t.frame_samples == 320


def test_slices_chunk_into_canonical_frames():
    s = mk()
    # 3200 байт = 100мс = 5 фреймов по 640 байт
    n = s.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(3200))
    assert n == 5
    t = s.tracks["p"]
    assert t.frames_count == 5
    assert t.first_index == 5000          # round(100000/20)
    assert t.last_index == 5004


def test_exact_pcm_bytes_preserved():
    # ingest НЕ искажает PCM: конкатенация фреймов == вход (для кратного объёма)
    s = mk()
    data = pcm(3200)
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=data)
    frames = s.track_window("p")
    joined = b"".join(f.pcm for f in frames)
    assert joined == data


def test_residual_carried_across_contiguous_chunks():
    s = mk()
    # 700 байт (=21.875мс) → 1 фрейм + 60 байт residual
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(700))
    t = s.tracks["p"]
    assert t.frames_count == 1
    assert len(t.residual) == 60
    # следующий чанк продолжает по времени (T + ~22мс) → residual склеивается
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=100022, arrival_ms=100022, pcm=pcm(580))
    assert t.frames_count == 2
    assert len(t.residual) == 0


# --- discontinuity / gaps ---

def test_discontinuity_reanchors_and_counts_gap():
    s = mk()
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(700))
    t = s.tracks["p"]
    assert len(t.residual) == 60
    # большой скачок времени → разрыв: residual сбрасывается, gap++
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=105000, arrival_ms=105000, pcm=pcm(640))
    assert t.gaps_count == 1
    assert t.frames_count == 2          # 1 (до) + 1 (после re-anchor)


# --- duplicates / out-of-order (по seq) ---

def test_duplicate_seq_dropped():
    s = mk()
    s.ingest("x", ROLE_SECONDARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(640), seq=5)
    n = s.ingest("x", ROLE_SECONDARY, server_ts_ms=100020, arrival_ms=100020, pcm=pcm(640), seq=3)
    assert n == 0
    assert s.tracks["x"].duplicates_count == 1


# --- window bound ---

def test_window_bound_evicts_old_frames():
    s = mk(multi_source_ingest_window_seconds=1)  # max_frames = 50
    for i in range(60):  # 60 фреймов по 640 байт, по одному чанку
        s.ingest("p", ROLE_PRIMARY, server_ts_ms=100000 + i * 20, arrival_ms=100000 + i * 20, pcm=pcm(640))
    t = s.tracks["p"]
    assert t.frames_count == 60               # cumulative растёт
    assert len(t.frames) <= s.max_frames      # окно ограничено


# --- cross-track alignment (главный результат) ---

def test_cross_track_alignment_common_range():
    s = mk()
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(3200))   # idx 5000..5004
    s.ingest("x", ROLE_SECONDARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(3200), seq=1)
    common = s.common_index_range()
    assert common == (5000, 5004)
    aligned = s.aligned_window(5000, 5004)
    assert set(aligned.keys()) == {"p", "x"}
    assert len(aligned["p"]) == 5 and len(aligned["x"]) == 5
    # фреймы с одинаковым index → один и тот же интервал времени
    assert aligned["p"][0].frame_index == aligned["x"][0].frame_index == 5000


def test_partial_overlap_common_range():
    s = mk()
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(3200))   # 5000..5004
    s.ingest("x", ROLE_SECONDARY, server_ts_ms=100040, arrival_ms=100040, pcm=pcm(3200), seq=1)  # 5002..5006
    common = s.common_index_range()
    assert common == (5002, 5004)


# --- guards ---

def test_disabled_ingest_noop():
    s = mk(multi_source_ingest_enabled=False)
    assert s.ingest("p", ROLE_PRIMARY, server_ts_ms=1, arrival_ms=1, pcm=pcm(640)) == 0


def test_max_tracks_limit():
    s = mk(multi_source_ingest_max_tracks=1)
    assert s.register_track("a", ROLE_PRIMARY) is not None
    assert s.register_track("b", ROLE_SECONDARY) is None


def test_empty_pcm_noop():
    s = mk()
    assert s.ingest("p", ROLE_PRIMARY, server_ts_ms=1, arrival_ms=1, pcm=b"") == 0


# --- регресс: backward server_ts (re-sync/NTP) не должен ломать min/max индексы ---

def test_indices_correct_after_backward_server_ts():
    s = mk()
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(3200))  # 5000..5004
    t = s.tracks["p"]
    true_max = max(t.frames)
    # скачок времени назад → re-anchor на меньший index (вставка не в хвост по времени)
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=99000, arrival_ms=100100, pcm=pcm(640))     # 4950
    assert t.last_index == max(t.frames) == true_max   # не «последний вставленный»
    assert t.first_index == min(t.frames)


def test_common_range_correct_after_backward_jump_multitrack():
    s = mk()
    s.ingest("p", ROLE_PRIMARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(3200))            # 5000..5004
    s.ingest("x", ROLE_SECONDARY, server_ts_ms=100000, arrival_ms=100000, pcm=pcm(3200), seq=1)   # 5000..5004
    s.ingest("x", ROLE_SECONDARY, server_ts_ms=99000, arrival_ms=100100, pcm=pcm(640), seq=2)     # 4950
    # перекрытие по-прежнему 5000..5004, а не None из-за рассинхрона order
    assert s.common_index_range() == (5000, 5004)
