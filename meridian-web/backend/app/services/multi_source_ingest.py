"""Multi-source ingest (Этап 9.3) — единая server timeline для всех аудиоисточников.

Все аудиопотоки встречи (primary active-source + secondary shadow) приводятся к ОДНОЙ
server timeline и режутся на canonical frames фиксированной длительности. Frame получает
АБСОЛЮТНЫЙ frame_index на общей сетке (`round(server_ms / frame_ms)`), поэтому фреймы
разных устройств с одинаковым frame_index относятся к одному и тому же интервалу —
это и есть «главный результат» этапа: backend знает соответствие фреймов по времени.

Каждый трек имеет СОБСТВЕННЫЙ ограниченный jitter/window-буфер canonical-фреймов
(reorder между фреймами одного трека не нужен — WS поверх TCP упорядочен; джиттер прихода
не двигает frame_index, т.к. индекс берётся из server-времени захвата). Считаются
gaps / duplicates / late frames / jitter / drift. Окно PCM ОГРАНИЧЕНО.

Жёсткие границы этапа 9.3 (не нарушать):
  - не делает interleaved multi-channel (mux);
  - не вставляет silence;
  - не отправляет secondary в STT;
  - не сохраняет PCM на диск/S3;
  - НЕ хранит второй большой PCM-буфер secondary — единственное место хранения PCM
    secondary-канала здесь (9.2 ring buffer теперь держит только метаданные).

Сервис «почти чистый»: время берётся из аргументов (server_ts_ms / arrival_ms), системные
часы внутри логики не дёргаются — детерминирован и тестируем.
"""

import logging
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("meridian.ingest")

# несоответствие server-времени продолжению потока больше этого → разрыв (re-anchor)
def _discontinuity_ms(frame_ms: int) -> int:
    return max(frame_ms, 40)

_JITTER_ALPHA = 0.2
_DRIFT_ALPHA = 0.2

ROLE_PRIMARY = "primary"
ROLE_SECONDARY = "secondary"


def _bytes_per_sample(codec: str) -> int:
    return 4 if codec == "float32" else 2


@dataclass
class CanonicalFrame:
    track_id: str
    frame_index: int
    server_ms: int
    samples: int
    pcm: bytes  # ровно frame_bytes байт


@dataclass
class IngestTrackState:
    track_id: str
    role: str
    side_hint: str | None
    sample_rate: int
    channels: int
    codec: str
    frame_bytes: int
    frame_samples: int
    frames_count: int = 0      # суммарно emitted (растёт)
    gaps_count: int = 0
    duplicates_count: int = 0
    late_frames: int = 0
    jitter_ms: float = 0.0
    drift_ms: float = 0.0
    last_seq: int | None = None
    last_client_ts_ms: int | None = None
    last_server_ts_ms: int | None = None
    last_arrival_ms: int | None = None
    # внутреннее состояние реконструкции
    residual: bytearray = field(default_factory=bytearray)
    cursor_index: int | None = None
    expected_next_ms: float | None = None
    frames: dict = field(default_factory=dict)        # frame_index -> CanonicalFrame
    order: deque = field(default_factory=deque)        # порядок индексов (для эвикта)

    @property
    def first_index(self) -> int | None:
        # min/max берём из самих фреймов: при backward server_ts (re-sync/NTP) порядок
        # вставки в order может быть не монотонным, поэтому order[0]/[-1] != min/max.
        # Дёргается только на throttled ~1с diag-пути, не в hot-loop.
        return min(self.frames) if self.frames else None

    @property
    def last_index(self) -> int | None:
        return max(self.frames) if self.frames else None


# --- Этап 9.4: immutable snapshot для offline-экспорта (ingest НЕ мутируется) ---

@dataclass(frozen=True)
class AudioTrackFrameSnapshot:
    track_id: str
    connection_id: str
    generation: int
    source_kind: str            # = role (primary|secondary)
    side_hint: str | None
    status: str                 # ready|stale|empty
    sample_rate: int
    frame_ms: int
    first_index: int | None     # глобальный диапазон трека на момент снимка
    last_index: int | None
    frames: dict                # {frame_index: bytes} — ТОЛЬКО кадры окна, bytes immutable
    diagnostics: dict


@dataclass(frozen=True)
class MultiSourceWindowSnapshot:
    created_server_ms: int
    sample_rate: int
    frame_ms: int
    start_index: int
    end_index: int              # exclusive
    tracks: tuple               # tuple[AudioTrackFrameSnapshot, ...]


@dataclass(frozen=True)
class MultiTrackFrameRead:
    """Этап 9.6: один frame_index по нескольким трекам (realtime mux). O(каналов)."""
    frame_index: int
    frame_start_server_ms: int
    frame_end_server_ms: int
    tracks: tuple               # tuple[tuple[track_id, bytes | None], ...] в порядке track_ids


class MultiSourceIngest:
    """Единый ingest-слой одной встречи (in-memory, эфемерно, окно ограничено)."""

    def __init__(self, settings) -> None:
        self.enabled: bool = settings.multi_source_ingest_enabled
        self.frame_ms: int = max(1, settings.multi_source_ingest_frame_ms)
        self.window_ms: int = max(self.frame_ms, settings.multi_source_ingest_window_seconds * 1000)
        self.max_tracks: int = settings.multi_source_ingest_max_tracks
        self.max_frames: int = max(1, self.window_ms // self.frame_ms)
        self.tracks: dict[str, IngestTrackState] = {}

    # --- lifecycle ---

    def register_track(self, track_id: str, role: str, *, side_hint: str | None = None,
                       sample_rate: int = 16000, channels: int = 1,
                       codec: str = "pcm16") -> IngestTrackState | None:
        t = self.tracks.get(track_id)
        if t is not None:
            t.role = role
            if side_hint is not None:
                t.side_hint = side_hint
            return t
        if len(self.tracks) >= self.max_tracks:
            return None
        t = IngestTrackState(
            track_id=track_id, role=role, side_hint=side_hint,
            sample_rate=sample_rate, channels=channels, codec=codec,
            frame_bytes=self._frame_bytes(sample_rate, channels, codec),
            frame_samples=int(round(sample_rate * self.frame_ms / 1000.0)),
        )
        self.tracks[track_id] = t
        return t

    def remove_track(self, track_id: str) -> None:
        self.tracks.pop(track_id, None)

    def set_side_hint(self, track_id: str, side_hint: str | None) -> None:
        t = self.tracks.get(track_id)
        if t is not None:
            t.side_hint = side_hint

    def _frame_bytes(self, sample_rate: int, channels: int, codec: str) -> int:
        return int(round(sample_rate * self.frame_ms / 1000.0)) * _bytes_per_sample(codec) * max(1, channels)

    # --- ingest ---

    def ingest(self, track_id: str, role: str, *, server_ts_ms: int, arrival_ms: int,
               pcm: bytes, sample_rate: int = 16000, channels: int = 1,
               codec: str = "pcm16", seq: int | None = None,
               client_ts_ms: int | None = None, side_hint: str | None = None) -> int:
        """Принять PCM-чанк источника и нарезать на canonical frames.

        Возвращает число новых emitted canonical frames. Не бросает исключений
        наружу при пустом/битом payload. PCM/PII в лог не пишутся.
        """
        if not self.enabled:
            return 0
        t = self.tracks.get(track_id)
        if t is None:
            t = self.register_track(track_id, role, side_hint=side_hint,
                                    sample_rate=sample_rate, channels=channels, codec=codec)
            if t is None:
                return 0
        if side_hint is not None:
            t.side_hint = side_hint

        # формат мог уточниться
        if (sample_rate, channels, codec) != (t.sample_rate, t.channels, t.codec):
            t.sample_rate, t.channels, t.codec = sample_rate, channels, codec
            t.frame_bytes = self._frame_bytes(sample_rate, channels, codec)
            t.frame_samples = int(round(sample_rate * self.frame_ms / 1000.0))

        stride = _bytes_per_sample(codec) * max(1, channels)
        if not pcm or t.frame_bytes <= 0 or len(pcm) < stride:
            return 0

        # дубликаты / out-of-order на уровне чанка (TCP упорядочен; защита от баг-клиента)
        if seq is not None and t.last_seq is not None and seq <= t.last_seq:
            t.duplicates_count += 1
            return 0

        chunk_samples = len(pcm) // stride
        duration_ms = chunk_samples * 1000.0 / max(1, sample_rate)

        # jitter: |межкадровый интервал прихода − длительность аудио|
        if t.last_arrival_ms is not None:
            inter = arrival_ms - t.last_arrival_ms
            t.jitter_ms = round(_JITTER_ALPHA * abs(inter - duration_ms) + (1 - _JITTER_ALPHA) * t.jitter_ms, 2)
        # drift: расхождение хода server-времени захвата и длительности произведённого аудио
        if t.last_server_ts_ms is not None:
            advance = server_ts_ms - t.last_server_ts_ms
            t.drift_ms = round(_DRIFT_ALPHA * (advance - duration_ms) + (1 - _DRIFT_ALPHA) * t.drift_ms, 2)

        # contiguity / re-anchor к общей сетке
        disc = _discontinuity_ms(self.frame_ms)
        if t.cursor_index is None or t.expected_next_ms is None \
                or abs(server_ts_ms - t.expected_next_ms) > disc:
            if t.expected_next_ms is not None and server_ts_ms - t.expected_next_ms > disc:
                t.gaps_count += 1
            t.residual.clear()
            t.cursor_index = int(round(server_ts_ms / self.frame_ms))

        t.residual.extend(pcm)
        emitted = 0
        while len(t.residual) >= t.frame_bytes:
            piece = bytes(t.residual[:t.frame_bytes])
            del t.residual[:t.frame_bytes]
            idx = t.cursor_index
            t.cursor_index += 1
            if self._emit_frame(t, idx, piece):
                emitted += 1

        t.expected_next_ms = server_ts_ms + duration_ms
        t.last_seq = seq
        t.last_client_ts_ms = client_ts_ms
        t.last_server_ts_ms = server_ts_ms
        t.last_arrival_ms = arrival_ms
        return emitted

    def _emit_frame(self, t: IngestTrackState, idx: int, pcm: bytes) -> bool:
        if idx in t.frames:
            t.duplicates_count += 1
            return False
        # пришёл фрейм старше окна (уже эвикчен) → late, дропаем
        if t.order and idx < t.order[0] and len(t.frames) >= self.max_frames:
            t.late_frames += 1
            return False
        t.frames[idx] = CanonicalFrame(
            track_id=t.track_id, frame_index=idx, server_ms=idx * self.frame_ms,
            samples=t.frame_samples, pcm=pcm,
        )
        # order — ТОЛЬКО для эвикта (FIFO по вставке ≈ старейшее). Корректность min/max
        # обеспечивается first_index/last_index (по ключам frames), не порядком order.
        t.order.append(idx)
        t.frames_count += 1
        # эвикт по окну (множества order и frames остаются согласованными)
        while len(t.frames) > self.max_frames and t.order:
            old = t.order.popleft()
            t.frames.pop(old, None)
        return True

    # --- aligned queries (фундамент для 9.4/9.5/9.6) ---

    def _active_tracks(self) -> list[IngestTrackState]:
        return [t for t in self.tracks.values() if t.frames]

    def common_index_range(self) -> tuple[int, int] | None:
        """Перекрывающийся диапазон frame_index по ВСЕМ трекам с фреймами (или None)."""
        active = self._active_tracks()
        if len(active) < 1:
            return None
        lo = max(t.first_index for t in active)
        hi = min(t.last_index for t in active)
        if lo > hi:
            return None
        return lo, hi

    def track_window(self, track_id: str) -> list[CanonicalFrame]:
        t = self.tracks.get(track_id)
        if t is None:
            return []
        return [t.frames[i] for i in sorted(t.frames.keys())]

    def aligned_window(self, lo_index: int, hi_index: int) -> dict[str, list[CanonicalFrame]]:
        """Для каждого трека — его canonical frames в [lo_index, hi_index] (по возрастанию)."""
        out: dict[str, list[CanonicalFrame]] = {}
        for tid, t in self.tracks.items():
            frames = [t.frames[i] for i in range(lo_index, hi_index + 1) if i in t.frames]
            if frames:
                out[tid] = frames
        return out

    # --- diagnostics ---

    def track_diag(self, t: IngestTrackState) -> dict:
        return {
            "track_id": t.track_id,
            "role": t.role,
            "side_hint": t.side_hint,
            "sample_rate": t.sample_rate,
            "channels": t.channels,
            "codec": t.codec,
            "frame_ms": self.frame_ms,
            "frame_bytes": t.frame_bytes,
            "frames_count": t.frames_count,
            "buffered_frames": len(t.frames),
            "gaps_count": t.gaps_count,
            "duplicates_count": t.duplicates_count,
            "late_frames": t.late_frames,
            "jitter_ms": t.jitter_ms,
            "drift_ms": t.drift_ms,
            "first_index": t.first_index,
            "last_index": t.last_index,
        }

    def alignment_summary(self) -> dict:
        common = self.common_index_range()
        return {
            "frame_ms": self.frame_ms,
            "window_ms": self.window_ms,
            "common_lo": common[0] if common else None,
            "common_hi": common[1] if common else None,
            "tracks": [self.track_diag(t) for t in self.tracks.values()],
        }

    # --- Этап 9.6: read-only accessors для realtime mux (без snapshot, O(каналов)) ---

    def read_tracks_at_index(self, *, track_ids: list[str], frame_index: int) -> MultiTrackFrameRead:
        """PCM выбранных треков на одном frame_index. Порядок = track_ids; missing → None.

        Неизвестный track → KeyError. bytes immutable, ingest не мутируется.
        """
        out: list[tuple] = []
        for tid in track_ids:
            t = self.tracks.get(tid)
            if t is None:
                raise KeyError(tid)
            fr = t.frames.get(frame_index)
            out.append((tid, fr.pcm if fr is not None else None))
        return MultiTrackFrameRead(
            frame_index=frame_index,
            frame_start_server_ms=frame_index * self.frame_ms,
            frame_end_server_ms=(frame_index + 1) * self.frame_ms,
            tracks=tuple(out),
        )

    def get_track_range(self, track_id: str) -> tuple[int | None, int | None]:
        t = self.tracks.get(track_id)
        if t is None:
            return None, None
        return t.first_index, t.last_index

    def get_common_range(self, track_ids: list[str]) -> tuple[int | None, int | None]:
        firsts, lasts = [], []
        for tid in track_ids:
            t = self.tracks.get(tid)
            if t is None or t.first_index is None or t.last_index is None:
                return None, None
            firsts.append(t.first_index)
            lasts.append(t.last_index)
        if not firsts:
            return None, None
        lo, hi = max(firsts), min(lasts)
        if lo > hi:
            return None, None
        return lo, hi

    # --- Этап 9.4: безопасный snapshot API (ingest не мутируется) ---

    def _track_status(self, t: IngestTrackState, now_ms: int | None) -> str:
        if not t.frames:
            return "empty"
        if now_ms is not None and t.last_server_ts_ms is not None \
                and now_ms - t.last_server_ts_ms > 3000:
            return "stale"
        return "ready"

    def list_exportable_tracks(self, *, include_stopped: bool = False,
                               now_ms: int | None = None,
                               clock_quality_by_track: dict | None = None) -> list[dict]:
        """Лёгкий список треков для выбора окна/каналов (без копии PCM).

        include_stopped=False → только треки с буферизованными кадрами.
        """
        cq = clock_quality_by_track or {}
        out: list[dict] = []
        for tid, t in self.tracks.items():
            status = self._track_status(t, now_ms)
            if not include_stopped and status == "empty":
                continue
            diag = self.track_diag(t)
            diag["clock_quality"] = cq.get(tid)
            out.append({
                "track_id": tid,
                "connection_id": tid,
                "generation": 0,           # generation в ingest пока не отслеживается
                "source_kind": t.role,
                "side_hint": t.side_hint,
                "status": status,
                "sample_rate": t.sample_rate,
                "frame_ms": self.frame_ms,
                "first_index": t.first_index,
                "last_index": t.last_index,
                "buffered_frames": len(t.frames),
                "clock_quality": cq.get(tid),
                "diagnostics": diag,
            })
        return out

    def snapshot_window(self, *, track_ids: list[str], start_index: int, end_index: int,
                        now_ms: int, clock_quality_by_track: dict | None = None
                        ) -> MultiSourceWindowSnapshot:
        """Immutable-снимок [start_index, end_index) выбранных треков.

        end_index EXCLUSIVE. Копирует только кадры окна (bytes immutable, переиспользуются).
        НЕ меняет diagnostics/eviction/counters. Неизвестный track → KeyError.
        Вызывать синхронно (под event loop без await между чтениями) — атомарно к ingest.
        """
        if start_index >= end_index:
            raise ValueError("start_index must be < end_index")
        cq = clock_quality_by_track or {}
        snaps: list[AudioTrackFrameSnapshot] = []
        for tid in track_ids:
            t = self.tracks.get(tid)
            if t is None:
                raise KeyError(tid)
            window_frames = {
                i: t.frames[i].pcm
                for i in range(start_index, end_index)
                if i in t.frames
            }
            diag = self.track_diag(t)
            diag["clock_quality"] = cq.get(tid)
            snaps.append(AudioTrackFrameSnapshot(
                track_id=tid, connection_id=tid, generation=0, source_kind=t.role,
                side_hint=t.side_hint, status=self._track_status(t, now_ms),
                sample_rate=t.sample_rate, frame_ms=self.frame_ms,
                first_index=t.first_index, last_index=t.last_index,
                frames=window_frames, diagnostics=diag,
            ))
        return MultiSourceWindowSnapshot(
            created_server_ms=now_ms, sample_rate=(snaps[0].sample_rate if snaps else 16000),
            frame_ms=self.frame_ms, start_index=start_index, end_index=end_index,
            tracks=tuple(snaps),
        )
