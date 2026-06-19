"""Multi-channel WAV export (Этап 9.4) — диагностический WAV из ingest-окна.

Собирает многоканальный PCM16 WAV из immutable-снимка ingest-окна (см.
multi_source_ingest.snapshot_window): один track = один канал, каналы выровнены по
frame_index, пропуски заполняются тишиной ТОЛЬКО в файле, поддержан ручной sample-level
offset на канал. Чистые функции (без I/O, без event loop) — детерминированы и тестируемы.

Жёсткие границы: НЕ mux/STT/resampling/normalization/time-stretch; НЕ диск/БД/S3;
ingest-снимок не мутируется; PCM в лог/манифест не попадает.
"""

import struct
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ExportWindowMode = Literal["common", "last", "explicit"]

BITS_PER_SAMPLE = 16
BYTES_PER_SAMPLE = 2
WAV_HEADER_BYTES = 44
MAX_WAV_BYTES_HARD = 4 * 1024 * 1024 * 1024  # < 4 GiB (формат RIFF)

GAP_RATIO_WARN = 0.05
DRIFT_WARN_MS = 50.0
SHORT_DURATION_WARN_MS = 3000


class MultiChannelExportError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class MultiChannelTrackSelection:
    track_id: str
    channel_index: int
    label: str
    source_kind: str
    side_hint: str | None
    generation: int
    offset_ms: int = 0


@dataclass(frozen=True)
class MultiChannelExportPlan:
    sample_rate: int
    bits_per_sample: int
    channel_count: int
    block_align: int
    byte_rate: int

    start_index: int
    end_index: int
    frame_count: int
    frame_ms: int

    samples_per_channel: int
    data_bytes: int
    wav_bytes: int
    duration_ms: int

    channels: tuple

    available_frames_by_track: dict
    missing_frames_by_track: dict
    gap_ratio_by_track: dict
    diag_by_track: dict

    warnings: tuple


# --- helpers ---

def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def samples_per_frame(sample_rate: int, frame_ms: int) -> int:
    # round(), как в multi_source_ingest (frame_samples/frame_bytes), иначе при не-16к
    # частотах размер кадра разойдётся и реальные кадры сочтутся «повреждёнными».
    return int(round(sample_rate * frame_ms / 1000.0))


def _frames_for_seconds(seconds: int, frame_ms: int) -> int:
    return max(1, round(seconds * 1000 / frame_ms))


# --- channel ordering / labels ---

_PRIMARY_LABEL = "Основной канал"
_SHADOW_SELF = "Shadow — Мы"
_SHADOW_OPP = "Shadow — Не мы"
_SHADOW_UNK = "Shadow — сторона не указана"


def _group_rank(track: dict) -> int:
    kind = track.get("source_kind")
    side = track.get("side_hint")
    if kind == "primary":
        return 0 if track.get("is_active") else 1
    if side == "self":
        return 2
    if side == "opponent":
        return 3
    return 4


def default_channel_order(tracks: list[dict]) -> list[str]:
    """Детерминированный порядок каналов (см. spec): active primary, primary, shadow self,
    shadow opponent, shadow unknown; внутри группы по track_id."""
    ordered = sorted(tracks, key=lambda t: (_group_rank(t), str(t.get("track_id"))))
    return [str(t["track_id"]) for t in ordered]


def _base_label(source_kind: str, side_hint: str | None) -> str:
    if source_kind == "primary":
        return _PRIMARY_LABEL
    if side_hint == "self":
        return _SHADOW_SELF
    if side_hint == "opponent":
        return _SHADOW_OPP
    return _SHADOW_UNK


def _labels_with_disambiguation(selections: list[dict]) -> list[str]:
    base = [_base_label(s["source_kind"], s.get("side_hint")) for s in selections]
    counts: dict[str, int] = {}
    for b in base:
        counts[b] = counts.get(b, 0) + 1
    out = []
    for s, b in zip(selections, base):
        if counts[b] > 1:
            out.append(f"{b} (#{str(s['track_id'])[:6]})")
        else:
            out.append(b)
    return out


# --- window resolution ---

def resolve_export_window(
    *,
    tracks: list[dict],
    mode: ExportWindowMode,
    frame_ms: int,
    default_seconds: int,
    max_seconds: int,
    duration_seconds: int | None = None,
    start_server_ms: int | None = None,
    end_server_ms: int | None = None,
) -> tuple[int, int]:
    """Вернуть (start_index, end_index) — end EXCLUSIVE. На основе ingest timeline (не wall clock)."""
    valid = [t for t in tracks
             if t.get("first_index") is not None and t.get("last_index") is not None]
    if not valid:
        raise MultiChannelExportError("NO_AUDIO_DATA", "Нет аудиоданных для экспорта")

    if duration_seconds is not None and not _is_int(duration_seconds):
        raise MultiChannelExportError("INVALID_WINDOW", "duration_seconds должен быть целым")

    if mode == "common":
        lo = max(t["first_index"] for t in valid)
        hi_excl = min(t["last_index"] for t in valid) + 1
        if lo >= hi_excl:
            raise MultiChannelExportError("NO_COMMON_WINDOW", "Нет общего окна каналов")
        if duration_seconds:
            dur = _frames_for_seconds(min(duration_seconds, max_seconds), frame_ms)
            start = max(lo, hi_excl - dur)
        elif (hi_excl - lo) * frame_ms > max_seconds * 1000:
            start = hi_excl - _frames_for_seconds(max_seconds, frame_ms)
        else:
            start = lo
        return start, hi_excl

    if mode == "last":
        end_excl = max(t["last_index"] for t in valid) + 1
        global_min = min(t["first_index"] for t in valid)
        dur_s = duration_seconds if duration_seconds else default_seconds
        if dur_s <= 0:
            raise MultiChannelExportError("INVALID_WINDOW", "duration must be > 0")
        dur_s = min(dur_s, max_seconds)
        start = max(end_excl - _frames_for_seconds(dur_s, frame_ms), global_min)
        if start >= end_excl:
            raise MultiChannelExportError("NO_AUDIO_DATA", "Пустое окно")
        return start, end_excl

    if mode == "explicit":
        if not _is_int(start_server_ms) or not _is_int(end_server_ms):
            raise MultiChannelExportError("INVALID_WINDOW", "explicit требует start/end server ms (int)")
        start_index = start_server_ms // frame_ms
        end_index = -(-end_server_ms // frame_ms)  # ceil
        if end_index <= start_index:
            raise MultiChannelExportError("INVALID_WINDOW", "end должен быть больше start")
        # ВАЖНО: ограничить окно ДО snapshot — иначе snapshot_window прокрутит гигантский
        # range() синхронно на event loop (DoS). Лимит проверяем на маленьких int.
        if (end_index - start_index) * frame_ms > max_seconds * 1000:
            raise MultiChannelExportError("DURATION_LIMIT", f"Длительность превышает {max_seconds} с")
        overlap = any(
            not (t["last_index"] < start_index or t["first_index"] >= end_index)
            for t in valid
        )
        if not overlap:
            raise MultiChannelExportError("NO_AUDIO_DATA", "Интервал не пересекается ни с одним каналом")
        return start_index, end_index

    raise MultiChannelExportError("INVALID_WINDOW", f"Неизвестный режим окна: {mode}")


# --- plan ---

def build_export_plan(
    *,
    snapshot,
    ordered_track_ids: list[str],
    offsets_ms: dict | None,
    max_channels: int,
    max_seconds: int,
    max_bytes: int,
    max_offset_ms: int,
) -> MultiChannelExportPlan:
    offsets_ms = offsets_ms or {}
    if not ordered_track_ids:
        raise MultiChannelExportError("NO_TRACKS", "Не выбран ни один канал")
    if len(ordered_track_ids) > max_channels:
        raise MultiChannelExportError("TOO_MANY_CHANNELS", f"Максимум каналов: {max_channels}")

    by_id = {t.track_id: t for t in snapshot.tracks}
    selected = []
    for tid in ordered_track_ids:
        t = by_id.get(tid)
        if t is None:
            raise MultiChannelExportError("TRACK_NOT_FOUND", f"Трек не найден: {tid}")
        selected.append(t)

    sample_rate = snapshot.sample_rate
    frame_ms = snapshot.frame_ms
    for t in selected:
        if t.sample_rate != sample_rate or t.frame_ms != frame_ms:
            raise MultiChannelExportError("SAMPLE_RATE_MISMATCH",
                                          "Каналы имеют разный sample_rate/frame_ms")

    # offsets: int, не bool, в допустимом диапазоне
    for tid, off in offsets_ms.items():
        if not _is_int(off):
            raise MultiChannelExportError("INVALID_OFFSET", f"offset должен быть int: {tid}")
        if abs(off) > max_offset_ms:
            raise MultiChannelExportError("INVALID_OFFSET",
                                          f"offset вне диапазона ±{max_offset_ms} мс: {tid}")

    start_index = snapshot.start_index
    end_index = snapshot.end_index
    frame_count = end_index - start_index
    if frame_count <= 0:
        raise MultiChannelExportError("INVALID_WINDOW", "Пустое окно")

    spf = samples_per_frame(sample_rate, frame_ms)
    canonical_frame_bytes = spf * BYTES_PER_SAMPLE
    samples_per_channel = frame_count * spf
    channel_count = len(selected)
    block_align = channel_count * BYTES_PER_SAMPLE
    byte_rate = sample_rate * block_align
    data_bytes = samples_per_channel * block_align
    wav_bytes = WAV_HEADER_BYTES + data_bytes
    duration_ms = frame_count * frame_ms

    if duration_ms > max_seconds * 1000:
        raise MultiChannelExportError("DURATION_LIMIT", f"Длительность превышает {max_seconds} с")
    if wav_bytes > max_bytes or wav_bytes >= MAX_WAV_BYTES_HARD:
        raise MultiChannelExportError("BYTE_LIMIT", "Файл превышает допустимый размер")

    # available/missing — только кадры канонического размера в окне
    available_by, missing_by, gap_by, diag_by = {}, {}, {}, {}
    total_available = 0
    sel_dicts = []
    for ch_idx, t in enumerate(selected):
        avail = sum(1 for i in range(start_index, end_index)
                    if i in t.frames and len(t.frames[i]) == canonical_frame_bytes)
        total_available += avail
        available_by[t.track_id] = avail
        missing_by[t.track_id] = frame_count - avail
        gap_by[t.track_id] = round((frame_count - avail) / frame_count, 4) if frame_count else 0.0
        diag_by[t.track_id] = {
            "clock_quality": t.diagnostics.get("clock_quality"),
            "jitter_ms": t.diagnostics.get("jitter_ms"),
            "drift_ms": t.diagnostics.get("drift_ms"),
            "status": t.status,
        }
        sel_dicts.append({"track_id": t.track_id, "source_kind": t.source_kind,
                          "side_hint": t.side_hint})

    if total_available == 0:
        raise MultiChannelExportError("NO_AUDIO_DATA", "В окне нет ни одного кадра")

    labels = _labels_with_disambiguation(sel_dicts)
    channels = []
    warnings: list[str] = []
    for ch_idx, t in enumerate(selected):
        off = int(offsets_ms.get(t.track_id, 0))
        channels.append(MultiChannelTrackSelection(
            track_id=t.track_id, channel_index=ch_idx, label=labels[ch_idx],
            source_kind=t.source_kind, side_hint=t.side_hint,
            generation=t.generation, offset_ms=off,
        ))
        if gap_by[t.track_id] > GAP_RATIO_WARN:
            warnings.append(f"Канал «{labels[ch_idx]}»: пропусков {gap_by[t.track_id] * 100:.0f}%")
        cq = diag_by[t.track_id]["clock_quality"]
        if cq in ("poor", None, "unknown"):
            warnings.append(f"Канал «{labels[ch_idx]}»: качество синхронизации часов — {cq or 'неизвестно'}")
        if t.status in ("stale", "error", "poor"):
            warnings.append(f"Канал «{labels[ch_idx]}»: статус {t.status}")
        drift = diag_by[t.track_id]["drift_ms"]
        if drift is not None and abs(drift) > DRIFT_WARN_MS:
            warnings.append(f"Канал «{labels[ch_idx]}»: дрейф {drift:.0f} мс")
        if off != 0:
            warnings.append(f"Канал «{labels[ch_idx]}»: ручной сдвиг {off} мс")
    if duration_ms < SHORT_DURATION_WARN_MS:
        warnings.append("Короткое окно (< 3 с) — диагностическая ценность ограничена")

    return MultiChannelExportPlan(
        sample_rate=sample_rate, bits_per_sample=BITS_PER_SAMPLE, channel_count=channel_count,
        block_align=block_align, byte_rate=byte_rate,
        start_index=start_index, end_index=end_index, frame_count=frame_count, frame_ms=frame_ms,
        samples_per_channel=samples_per_channel, data_bytes=data_bytes, wav_bytes=wav_bytes,
        duration_ms=duration_ms, channels=tuple(channels),
        available_frames_by_track=available_by, missing_frames_by_track=missing_by,
        gap_ratio_by_track=gap_by, diag_by_track=diag_by, warnings=tuple(warnings),
    )


# --- WAV assembly ---

def build_pcm16_wav_header(*, sample_rate: int, channels: int, samples_per_channel: int) -> bytes:
    if not (1 <= channels <= 8):
        raise MultiChannelExportError("TOO_MANY_CHANNELS", "channels вне диапазона 1..8")
    block_align = channels * BYTES_PER_SAMPLE
    byte_rate = sample_rate * block_align
    data_bytes = samples_per_channel * block_align
    return b"".join([
        b"RIFF", struct.pack("<I", 36 + data_bytes), b"WAVE",
        b"fmt ", struct.pack("<I", 16), struct.pack("<H", 1), struct.pack("<H", channels),
        struct.pack("<I", sample_rate), struct.pack("<I", byte_rate),
        struct.pack("<H", block_align), struct.pack("<H", BITS_PER_SAMPLE),
        b"data", struct.pack("<I", data_bytes),
    ])


def build_channel_pcm16(
    *,
    track,
    start_index: int,
    end_index: int,
    sample_rate: int,
    frame_ms: int,
    offset_ms: int,
) -> bytes:
    """Mono PCM16 канала: окно [start,end) с тишиной на пропусках + sample-level offset.

    Длина результата ВСЕГДА samples_per_channel*2 байт (offset не меняет длину).
    """
    spf = samples_per_frame(sample_rate, frame_ms)
    frame_bytes = spf * BYTES_PER_SAMPLE
    silence_frame = b"\x00" * frame_bytes
    buf = bytearray()
    for i in range(start_index, end_index):
        fr = track.frames.get(i)
        if fr is not None and len(fr) == frame_bytes:
            buf += fr
        else:
            buf += silence_frame  # отсутствует ИЛИ повреждён → тишина
    total_bytes = (end_index - start_index) * frame_bytes

    offset_samples = round(offset_ms * sample_rate / 1000)
    offset_bytes = offset_samples * BYTES_PER_SAMPLE
    if offset_bytes == 0:
        return bytes(buf)
    if offset_bytes > 0:  # канал позже → тишина спереди, хвост обрезается
        if offset_bytes >= total_bytes:
            return b"\x00" * total_bytes
        return b"\x00" * offset_bytes + bytes(buf[:total_bytes - offset_bytes])
    ob = -offset_bytes      # канал раньше → срез спереди, тишина в хвост
    if ob >= total_bytes:
        return b"\x00" * total_bytes
    return bytes(buf[ob:]) + b"\x00" * ob


def interleave_pcm16_channels(channels_pcm: list[bytes]) -> bytes:
    if not channels_pcm:
        return b""
    n = len(channels_pcm[0])
    for c in channels_pcm:
        if len(c) != n:
            raise MultiChannelExportError("INVALID_WINDOW", "Каналы разной длины")
    if n % BYTES_PER_SAMPLE != 0:
        raise MultiChannelExportError("INVALID_WINDOW", "Длина PCM не кратна 2")
    cc = len(channels_pcm)
    if cc == 1:
        return bytes(channels_pcm[0])
    mono_samples = n // BYTES_PER_SAMPLE
    out = bytearray(mono_samples * cc * BYTES_PER_SAMPLE)
    out_view = memoryview(out).cast("h")  # int16; копируем сэмплы strided, байты сохраняются
    for ch, buf in enumerate(channels_pcm):
        out_view[ch::cc] = memoryview(buf).cast("h")
    return bytes(out)


def build_multi_channel_wav(*, snapshot, plan: MultiChannelExportPlan) -> bytes:
    by_id = {t.track_id: t for t in snapshot.tracks}
    monos = []
    for sel in plan.channels:
        track = by_id[sel.track_id]
        monos.append(build_channel_pcm16(
            track=track, start_index=plan.start_index, end_index=plan.end_index,
            sample_rate=plan.sample_rate, frame_ms=plan.frame_ms, offset_ms=sel.offset_ms,
        ))
    interleaved = interleave_pcm16_channels(monos)
    header = build_pcm16_wav_header(
        sample_rate=plan.sample_rate, channels=plan.channel_count,
        samples_per_channel=plan.samples_per_channel,
    )
    result = header + interleaved
    if len(result) != plan.wav_bytes:
        raise MultiChannelExportError("INVALID_WINDOW",
                                      f"Размер WAV {len(result)} != плана {plan.wav_bytes}")
    return result


# --- manifest ---

def export_plan_to_manifest(plan: MultiChannelExportPlan, *, meeting_id: int,
                            created_at: datetime) -> dict:
    """JSON-описание экспорта (БЕЗ PCM)."""
    return {
        "meeting_id": meeting_id,
        "created_at": created_at.isoformat(),
        "format": "pcm_s16le_wav",
        "sample_rate": plan.sample_rate,
        "bits_per_sample": plan.bits_per_sample,
        "channels_count": plan.channel_count,
        "duration_ms": plan.duration_ms,
        "start_server_ms": plan.start_index * plan.frame_ms,
        "end_server_ms": plan.end_index * plan.frame_ms,
        "frame_ms": plan.frame_ms,
        "data_bytes": plan.data_bytes,
        "wav_bytes": plan.wav_bytes,
        "channels": [
            {
                "channel_index": c.channel_index,
                "track_id": c.track_id,
                "label": c.label,
                "source_kind": c.source_kind,
                "side_hint": c.side_hint,
                "generation": c.generation,
                "offset_ms": c.offset_ms,
                "available_frames": plan.available_frames_by_track.get(c.track_id, 0),
                "missing_frames": plan.missing_frames_by_track.get(c.track_id, 0),
                "gap_ratio": plan.gap_ratio_by_track.get(c.track_id, 0.0),
                "clock_quality": plan.diag_by_track.get(c.track_id, {}).get("clock_quality"),
                "jitter_ms_p95": plan.diag_by_track.get(c.track_id, {}).get("jitter_ms"),
                "drift_ppm": plan.diag_by_track.get(c.track_id, {}).get("drift_ms"),
            }
            for c in plan.channels
        ],
        "warnings": list(plan.warnings),
    }
