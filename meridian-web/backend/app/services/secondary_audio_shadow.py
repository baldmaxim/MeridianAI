"""Secondary audio shadow (Этап 9.2) — приём аудио-чанков второго устройства БЕЗ STT.

Дополнительное устройство (`device_role=secondary`) стримит PCM-чанки одной встречи.
Backend буферизует их в in-memory ring buffer и считает диагностику канала, НО:
  - чанки НЕ идут в STT;
  - НЕ меняют active_audio_source;
  - это подготовка к Этапу 9.3 (server-side multi-source ingestion).

Это ОТДЕЛЬНЫЙ режим от observer-диаризации:
  observer            → только RMS/peak/VAD (числа);
  secondary_audio_shadow → реальные аудио-чанки (для будущего multi-channel).
Режимы не смешиваются (разные device_role, разные буферы).

Сервис намеренно «почти чистый»: вся логика времени принимается аргументом `now_ms`
(или server_ts_ms), системные часы внутри расчётов не дёргаются — легко тестировать.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("meridian.shadow")

# нет «нового кадра дольше ожидаемого + допуск» → считаем пропуск (gap)
GAP_TOLERANCE_MS = 120
# канал считается протухшим, если давно не было кадров
STALE_AFTER_MS = 3000
# сглаживание drift-хинта
_DRIFT_ALPHA = 0.2
# жёсткий потолок числа чанков в ring buffer (защита от роста при duration≈0):
# исходим из минимально вменяемой длительности чанка
_MIN_CHUNK_MS_FOR_CAP = 20

ACCEPTED_CODECS = ("pcm16", "float32")


@dataclass
class SecondaryAudioChunk:
    connection_id: str
    user_id: int | None
    seq: int
    client_ts_ms: int | None
    server_ts_ms: int
    sample_rate: int
    channels: int
    codec: str  # "pcm16" | "float32"
    duration_ms: int
    payload_bytes: int
    rms: float | None = None
    peak: float | None = None


@dataclass
class SecondaryAudioTrackState:
    connection_id: str
    user_id: int | None
    enabled: bool
    side_hint: str | None
    sample_rate: int | None
    channels: int | None
    codec: str | None
    chunks_count: int = 0
    bytes_count: int = 0
    dropped_chunks: int = 0
    gaps_count: int = 0
    last_seq: int | None = None
    last_client_ts_ms: int | None = None
    last_server_ts_ms: int | None = None
    last_duration_ms: int | None = None
    last_seen_at: datetime | None = None
    estimated_buffer_ms: int = 0
    drift_ms: float = 0.0
    status: str = "idle"  # idle | recording | stale | error
    error: str | None = None


def _bytes_per_sample(codec: str) -> int:
    return 4 if codec == "float32" else 2


def chunk_duration_ms(payload_bytes: int, sample_rate: int, channels: int, codec: str) -> int:
    """Длительность чанка по размеру PCM-пейлоада (mono pcm16 = 2 байта/сэмпл)."""
    ch = max(1, channels)
    sr = max(1, sample_rate)
    frames = payload_bytes / (_bytes_per_sample(codec) * ch)
    return int(round(frames / sr * 1000.0))


class SecondaryAudioShadow:
    """In-memory ring buffer аудио-чанков secondary-устройств одной встречи (эфемерно)."""

    def __init__(self, settings) -> None:
        self.enabled: bool = settings.secondary_audio_shadow_enabled
        self.max_devices: int = settings.secondary_audio_shadow_max_devices
        self.max_buffer_ms: int = settings.secondary_audio_shadow_max_buffer_seconds * 1000
        self.target_sample_rate: int = settings.secondary_audio_shadow_target_sample_rate
        self.max_chunk_ms: int = settings.secondary_audio_shadow_max_chunk_ms
        self.max_chunk_bytes: int = settings.secondary_audio_shadow_max_chunk_bytes
        # потолок числа чанков (независим от duration — защита от unbounded роста)
        self.max_chunks: int = max(1, (self.max_buffer_ms + _MIN_CHUNK_MS_FOR_CAP - 1)
                                   // _MIN_CHUNK_MS_FOR_CAP)
        self._accept: set[str] = set()
        if settings.secondary_audio_shadow_accept_pcm16:
            self._accept.add("pcm16")
        if settings.secondary_audio_shadow_accept_float32:
            self._accept.add("float32")
        self.tracks: dict[str, SecondaryAudioTrackState] = {}
        # ring buffer: connection_id -> deque[(chunk_meta, raw_payload)]
        self._buffers: dict[str, deque] = {}

    # --- lifecycle ---

    def register_track(self, connection_id: str, user_id: int | None,
                       side_hint: str | None = None) -> None:
        """Зарегистрировать idle-трек при подключении secondary-устройства."""
        if connection_id in self.tracks:
            return
        self.tracks[connection_id] = SecondaryAudioTrackState(
            connection_id=connection_id, user_id=user_id, enabled=False,
            side_hint=side_hint, sample_rate=None, channels=None, codec=None,
        )
        self._buffers[connection_id] = deque()

    def remove_track(self, connection_id: str) -> None:
        self.tracks.pop(connection_id, None)
        self._buffers.pop(connection_id, None)

    def _enabled_count(self, exclude: str | None = None) -> int:
        return sum(1 for cid, t in self.tracks.items()
                   if t.enabled and cid != exclude)

    def enable_track(self, connection_id: str, *, sample_rate: int, channels: int,
                     codec: str, side_hint: str | None = None) -> tuple[bool, str | None]:
        """Включить буферизацию трека. Возвращает (ok, error_reason|None)."""
        if not self.enabled:
            return False, "shadow_disabled"
        t = self.tracks.get(connection_id)
        if t is None:
            return False, "not_registered"
        codec = (codec or "").lower()
        if codec not in ACCEPTED_CODECS or codec not in self._accept:
            return False, "codec_rejected"
        try:
            sr = int(sample_rate)
            ch = int(channels)
        except (TypeError, ValueError):
            return False, "bad_format"
        if sr <= 0 or ch <= 0:
            return False, "bad_format"
        if not t.enabled and self._enabled_count(exclude=connection_id) >= self.max_devices:
            return False, "max_devices"
        t.enabled = True
        t.sample_rate = sr
        t.channels = ch
        t.codec = codec
        if side_hint is not None:
            t.side_hint = side_hint
        t.status = "idle"
        t.error = None
        return True, None

    def disable_track(self, connection_id: str) -> None:
        t = self.tracks.get(connection_id)
        if t is None:
            return
        t.enabled = False
        t.status = "idle"
        t.estimated_buffer_ms = 0
        # сброс непрерывности потока: после re-enable клиент стартует seq заново
        t.last_seq = None
        t.last_client_ts_ms = None
        t.last_server_ts_ms = None
        t.last_duration_ms = None
        t.drift_ms = 0.0
        buf = self._buffers.get(connection_id)
        if buf is not None:
            buf.clear()

    def set_side_hint(self, connection_id: str, side_hint: str | None) -> None:
        t = self.tracks.get(connection_id)
        if t is not None:
            t.side_hint = side_hint

    # --- ingest ---

    def add_chunk(self, connection_id: str, *, seq: int, client_ts_ms: int | None,
                  server_ts_ms: int, payload_bytes: int, payload: bytes | None,
                  sample_rate: int | None = None, channels: int | None = None,
                  codec: str | None = None, rms: float | None = None,
                  peak: float | None = None) -> tuple[bool, str | None]:
        """Принять один аудио-чанк. Возвращает (accepted, reject_reason|None).

        Никогда не пишет PII/байты в лог. Чанк кладётся в ring buffer (для 9.3).
        """
        if not self.enabled:
            return False, "shadow_disabled"
        t = self.tracks.get(connection_id)
        if t is None or not t.enabled:
            return False, "not_enabled"

        sr = int(sample_rate) if sample_rate else (t.sample_rate or self.target_sample_rate)
        ch = int(channels) if channels else (t.channels or 1)
        cod = (codec or t.codec or "pcm16").lower()

        # валидация payload
        if payload_bytes <= 0:
            t.dropped_chunks += 1
            return False, "empty"
        if payload_bytes > self.max_chunk_bytes:
            t.dropped_chunks += 1
            return False, "chunk_too_large"
        if cod not in self._accept:
            t.dropped_chunks += 1
            return False, "codec_rejected"

        duration_ms = chunk_duration_ms(payload_bytes, sr, ch, cod)
        if duration_ms > self.max_chunk_ms:
            t.dropped_chunks += 1
            return False, "chunk_too_long"
        # 0-мс чанк (крошечный payload) не вытесняется duration-триммером → отбрасываем
        if duration_ms <= 0:
            t.dropped_chunks += 1
            return False, "chunk_too_short"

        # out-of-order / дубликаты — отбрасываем
        if t.last_seq is not None and seq <= t.last_seq:
            t.dropped_chunks += 1
            return False, "out_of_order"

        # gap-детект (по seq или по времени)
        is_gap = False
        if t.last_seq is not None and seq > t.last_seq + 1:
            is_gap = True
        if t.last_server_ts_ms is not None:
            inter = server_ts_ms - t.last_server_ts_ms
            if inter > duration_ms + GAP_TOLERANCE_MS:
                is_gap = True
        if is_gap:
            t.gaps_count += 1

        # drift-хинт: расхождение хода client-часов и аудио-длительности
        if (t.last_client_ts_ms is not None and client_ts_ms is not None
                and not is_gap):
            client_delta = client_ts_ms - t.last_client_ts_ms
            instant = float(client_delta - duration_ms)
            t.drift_ms = round(_DRIFT_ALPHA * instant + (1 - _DRIFT_ALPHA) * t.drift_ms, 2)

        chunk = SecondaryAudioChunk(
            connection_id=connection_id, user_id=t.user_id, seq=seq,
            client_ts_ms=client_ts_ms, server_ts_ms=server_ts_ms,
            sample_rate=sr, channels=ch, codec=cod,
            duration_ms=duration_ms, payload_bytes=payload_bytes,
            rms=rms, peak=peak,
        )
        buf = self._buffers.setdefault(connection_id, deque())
        # Этап 9.3: полный PCM secondary хранит ingest-слой; здесь — только метаданные
        # чанка (чтобы не держать второй большой PCM-буфер). payload намеренно НЕ сохраняем.
        buf.append((chunk, b""))
        t.estimated_buffer_ms += duration_ms
        # trim ring buffer: по длительности И по жёсткому потолку числа чанков
        while buf and (t.estimated_buffer_ms > self.max_buffer_ms or len(buf) > self.max_chunks):
            old_chunk, _ = buf.popleft()
            t.estimated_buffer_ms = max(0, t.estimated_buffer_ms - old_chunk.duration_ms)

        # обновить состояние
        t.chunks_count += 1
        t.bytes_count += payload_bytes
        t.last_seq = seq
        t.last_client_ts_ms = client_ts_ms
        t.last_server_ts_ms = server_ts_ms
        t.last_duration_ms = duration_ms
        t.last_seen_at = datetime.utcnow()
        t.sample_rate = sr
        t.channels = ch
        t.codec = cod
        t.status = "recording"
        return True, None

    # --- diagnostics ---

    def _resolve_status(self, t: SecondaryAudioTrackState, now_ms: int) -> str:
        if not t.enabled:
            return "idle"
        if t.status == "error":
            return "error"
        if t.last_server_ts_ms is None:
            return "idle"
        if now_ms - t.last_server_ts_ms > STALE_AFTER_MS:
            return "stale"
        return "recording"

    def track_diag(self, connection_id: str, now_ms: int) -> dict | None:
        t = self.tracks.get(connection_id)
        if t is None:
            return None
        last_age = (now_ms - t.last_server_ts_ms) if t.last_server_ts_ms is not None else None
        return {
            "connection_id": t.connection_id,
            "enabled": t.enabled,
            "side_hint": t.side_hint,
            "status": self._resolve_status(t, now_ms),
            "sample_rate": t.sample_rate,
            "channels": t.channels,
            "codec": t.codec,
            "chunks_count": t.chunks_count,
            "bytes_count": t.bytes_count,
            "dropped_chunks": t.dropped_chunks,
            "gaps_count": t.gaps_count,
            "last_seq": t.last_seq,
            "last_duration_ms": t.last_duration_ms,
            "last_packet_age_ms": last_age,
            "estimated_buffer_ms": t.estimated_buffer_ms,
            "drift_ms": t.drift_ms,
            "target_sample_rate": self.target_sample_rate,
            "error": t.error,
        }

    def room_summary(self, now_ms: int) -> list[dict]:
        """Компактная сводка по трекам для broadcast в комнату (desktop-монитор)."""
        out = []
        for cid, t in self.tracks.items():
            out.append({
                "connection_id": cid,
                "side_hint": t.side_hint,
                "status": self._resolve_status(t, now_ms),
                "chunks_count": t.chunks_count,
                "estimated_buffer_ms": t.estimated_buffer_ms,
                "sample_rate": t.sample_rate,
            })
        return out
