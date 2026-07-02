"""Channel-aware audio frame v2 (MAUD2) — shadow transport (Этап 16).

Бинарный формат для опционального multichannel shadow-стрима. Legacy mono 16k frames (без
заголовка) остаются единственным production STT input — v2 frames только диагностика.

Формат кадра:
    [5 bytes MAGIC b"MAUD2"]
    [2 bytes uint16 BE header_length]
    [header JSON UTF-8]
    [payload PCM16 interleaved, little-endian]

Безопасность: payload (raw audio) НЕ логируется и НЕ хранится в trace — наружу идут только
агрегаты (rms/peak/clipping по каналам, счётчики). route/каналы — техническая зона записи, не сторона.
"""

import array
import json
import struct
import sys
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from .audio_capture_metadata import normalize_audio_capture_route

MAGIC = b"MAUD2"
MAX_HEADER_BYTES = 4096
MAX_FRAME_BYTES = 524288  # 512 KB
MAX_CHANNELS = 8
MIN_SAMPLE_RATE = 8000
MAX_SAMPLE_RATE = 96000
_CLIP_THRESHOLD = 0.98


class AudioFrameV2Header(BaseModel):
    model_config = ConfigDict(extra="ignore")

    protocol_version: int = 2
    sequence: int = 0
    sample_rate: int
    channels: int
    codec: Literal["pcm16"] = "pcm16"
    layout: Literal["interleaved"] = "interleaved"
    route: str = "unknown"
    capture_pipeline: str = "unknown"
    frame_duration_ms: Optional[int] = None
    source_is_isolated: bool = False
    created_at_ms: Optional[int] = None

    @field_validator("route", mode="before")
    @classmethod
    def _norm_route(cls, v):
        return normalize_audio_capture_route(v)

    @field_validator("capture_pipeline", mode="before")
    @classmethod
    def _norm_pipeline(cls, v):
        return v if v in ("multichannel_shadow_stream", "unknown") else "unknown"

    @field_validator("protocol_version")
    @classmethod
    def _check_version(cls, v):
        if v != 2:
            raise ValueError("protocol_version must be 2")
        return v

    @field_validator("channels")
    @classmethod
    def _check_channels(cls, v):
        if not (1 <= int(v) <= MAX_CHANNELS):
            raise ValueError("channels out of range")
        return int(v)

    @field_validator("sample_rate")
    @classmethod
    def _check_sample_rate(cls, v):
        if not (MIN_SAMPLE_RATE <= int(v) <= MAX_SAMPLE_RATE):
            raise ValueError("sample_rate out of range")
        return int(v)


@dataclass
class ParsedAudioFrameV2:
    header: AudioFrameV2Header
    payload: bytes = field(repr=False)  # raw audio — НЕ выводить в repr/лог
    sample_count_per_channel: int = 0
    duration_ms_estimate: float = 0.0
    rms_by_channel: list = field(default_factory=list)
    peak_by_channel: list = field(default_factory=list)
    clipping_by_channel: list = field(default_factory=list)

    def __repr__(self) -> str:  # без raw payload
        return (f"ParsedAudioFrameV2(channels={self.header.channels}, "
                f"samples_per_channel={self.sample_count_per_channel}, "
                f"payload_bytes={len(self.payload)})")


def is_audio_frame_v2(data: bytes) -> bool:
    """True, если буфер начинается с MAGIC и достаточно длинный для заголовка длины."""
    return isinstance(data, (bytes, bytearray)) and len(data) >= 7 and bytes(data[:5]) == MAGIC


def compute_pcm16_interleaved_stats(payload: bytes, channels: int) -> dict:
    """rms/peak/clipping по каждому каналу из interleaved PCM16 LE. Без хранения payload."""
    if channels <= 0:
        return {"rms": [], "peak": [], "clipping": []}
    n_samples = len(payload) // 2
    a = array.array("h")
    a.frombytes(bytes(payload[: n_samples * 2]))
    if sys.byteorder != "little":
        a.byteswap()
    sums = [0.0] * channels
    counts = [0] * channels
    peaks = [0] * channels
    for i in range(n_samples):
        c = i % channels
        s = a[i]
        v = s / 32768.0
        sums[c] += v * v
        counts[c] += 1
        av = -s if s < 0 else s
        if av > peaks[c]:
            peaks[c] = av
    rms = [round((sums[c] / counts[c]) ** 0.5, 4) if counts[c] else 0.0 for c in range(channels)]
    peak = [round(peaks[c] / 32768.0, 4) for c in range(channels)]
    clipping = [(peaks[c] / 32768.0) >= _CLIP_THRESHOLD for c in range(channels)]
    return {"rms": rms, "peak": peak, "clipping": clipping}


def parse_audio_frame_v2(data: bytes) -> ParsedAudioFrameV2:
    """Распарсить и провалидировать MAUD2 кадр. Бросает ValueError на любом нарушении."""
    if not is_audio_frame_v2(data):
        raise ValueError("bad magic")
    if len(data) > MAX_FRAME_BYTES:
        raise ValueError("frame too large")
    header_len = struct.unpack(">H", bytes(data[5:7]))[0]
    if header_len == 0 or header_len > MAX_HEADER_BYTES:
        raise ValueError("bad header length")
    h_end = 7 + header_len
    if h_end > len(data):
        raise ValueError("truncated header")
    try:
        hjson = json.loads(bytes(data[7:h_end]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"bad header json: {type(e).__name__}")
    if not isinstance(hjson, dict):
        raise ValueError("header is not an object")
    try:
        header = AudioFrameV2Header(**hjson)
    except Exception as e:  # pydantic ValidationError → единый ValueError
        raise ValueError(f"invalid header: {type(e).__name__}")
    payload = bytes(data[h_end:])
    block = 2 * header.channels
    if block <= 0 or len(payload) % block != 0:
        raise ValueError("payload not aligned to 2*channels")
    samples_per_channel = len(payload) // block
    stats = compute_pcm16_interleaved_stats(payload, header.channels)
    duration_ms = (samples_per_channel / header.sample_rate * 1000.0) if header.sample_rate else 0.0
    return ParsedAudioFrameV2(
        header=header, payload=payload, sample_count_per_channel=samples_per_channel,
        duration_ms_estimate=round(duration_ms, 3),
        rms_by_channel=stats["rms"], peak_by_channel=stats["peak"],
        clipping_by_channel=stats["clipping"])


def build_audio_frame_v2(header: dict, payload: bytes) -> bytes:
    """Собрать MAUD2 кадр из header dict + payload bytes (для тестов/симметрии с frontend)."""
    hbytes = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(hbytes) > MAX_HEADER_BYTES:
        raise ValueError("header too large")
    return MAGIC + struct.pack(">H", len(hbytes)) + hbytes + bytes(payload)
