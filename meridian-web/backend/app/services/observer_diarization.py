"""Observer-диаризация v1 (Этап 9).

Второй/дополнительный телефон — это observer: он НЕ шлёт raw audio и НЕ становится
активным STT-источником. Он локально считает уровень звука (RMS/peak/VAD) и шлёт только
числовые метрики. Пользователь указывает, возле какой стороны лежит устройство
(self = «рядом с нами», opponent = «рядом с другой стороной»).

Backend буферизует метрики по устройствам и вокруг committed-реплики сравнивает энергию
устройств «у нас» и «у них». При достаточной уверенности выдаёт подсказку
«реплика, вероятно, Мы / Не мы». Это только подсказка к слою corrections (Этап 8);
auto-apply по умолчанию выключен. Метрики эфемерны (в памяти комнаты).
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from .speaker_roles import to_public_side


@dataclass
class AudioLevelMetric:
    connection_id: str
    user_id: int | None
    side_hint: str | None  # self | opponent | None
    client_ts_ms: int | None
    server_ts: datetime
    rms: float
    peak: float | None = None
    vad: bool = False
    seq: int | None = None
    # Этап 9.1: момент захвата метрики, приведённый к server timeline (epoch ms) по
    # device-offset. Основа для будущего multi-channel alignment. None — устройство
    # ещё не синхронизировалось (или нет client_ts_ms).
    server_ts_ms: float | None = None


@dataclass
class ObserverDeviceState:
    connection_id: str
    user_id: int | None
    device_role: str
    side_hint: str | None
    enabled: bool
    last_rms: float
    last_peak: float | None
    last_vad: bool
    last_seen_at: datetime | None
    metrics_count: int = 0


@dataclass
class SegmentSideHint:
    segment_key: str
    side: str | None
    confidence: float
    reason: str
    self_energy: float
    opponent_energy: float
    unknown_energy: float
    device_count: int
    window_ms: int


def score_segment_side(
    self_energy: float, opponent_energy: float, unknown_energy: float, max_rms: float,
    *, min_rms: float, ratio: float, min_confidence: float,
) -> tuple[str | None, float, str]:
    """Pure-скоринг стороны реплики по агрегированной энергии устройств.

    Возвращает (side|None, confidence, reason). side=None — недостаточно уверенности.
    """
    if max_rms < min_rms:
        return None, 0.0, "too_quiet"
    dominant_side = "self" if self_energy >= opponent_energy else "opponent"
    dom = max(self_energy, opponent_energy)
    other = min(self_energy, opponent_energy)
    if dom <= 0:
        return None, 0.0, "no_signal"
    r = dom / other if other > 0 else float("inf")
    confidence = round(1.0 - (other / dom) if dom > 0 else 0.0, 3)
    if r < ratio or confidence < min_confidence:
        return None, confidence, "low_confidence"
    return dominant_side, min(confidence, 1.0), "level_ratio"


class ObserverDiarization:
    """In-memory буфер метрик observer-устройств одной встречи (эфемерно)."""

    def __init__(self, settings) -> None:
        self.enabled: bool = settings.observer_diarization_enabled
        self.auto_apply: bool = settings.observer_diarization_auto_apply
        self.window_ms: int = settings.observer_diarization_window_ms
        self.min_rms: float = settings.observer_diarization_min_rms
        self.ratio: float = settings.observer_diarization_ratio
        self.min_confidence: float = settings.observer_diarization_min_confidence
        self.max_metrics: int = settings.observer_diarization_max_metrics_per_device
        self.devices: dict[str, ObserverDeviceState] = {}
        self.metrics: dict[str, deque] = {}

    def register_device(self, connection_id: str, user_id: int | None,
                        device_role: str, side_hint: str | None = None) -> None:
        self.devices[connection_id] = ObserverDeviceState(
            connection_id=connection_id, user_id=user_id, device_role=device_role,
            side_hint=to_public_side(side_hint), enabled=True,
            last_rms=0.0, last_peak=None, last_vad=False, last_seen_at=None,
        )
        self.metrics[connection_id] = deque(maxlen=self.max_metrics)

    def set_side_hint(self, connection_id: str, side_hint: str | None) -> None:
        d = self.devices.get(connection_id)
        if d is not None:
            d.side_hint = to_public_side(side_hint)

    def remove_device(self, connection_id: str) -> None:
        self.devices.pop(connection_id, None)
        self.metrics.pop(connection_id, None)

    def add_metric(self, connection_id: str, *, rms: float, peak: float | None = None,
                   vad: bool = False, seq: int | None = None,
                   client_ts_ms: int | None = None, server_ts: datetime | None = None,
                   server_ts_ms: float | None = None) -> None:
        if not self.enabled:
            return
        d = self.devices.get(connection_id)
        if d is None:
            return
        ts = server_ts or datetime.utcnow()
        try:
            rms_v = max(0.0, float(rms))
        except (TypeError, ValueError):
            return
        peak_v = None
        if peak is not None:
            try:
                peak_v = max(0.0, float(peak))
            except (TypeError, ValueError):
                peak_v = None
        self.metrics[connection_id].append(AudioLevelMetric(
            connection_id=connection_id, user_id=d.user_id, side_hint=d.side_hint,
            client_ts_ms=client_ts_ms, server_ts=ts, rms=rms_v, peak=peak_v,
            vad=bool(vad), seq=seq, server_ts_ms=server_ts_ms,
        ))
        d.last_rms = rms_v
        d.last_peak = peak_v
        d.last_vad = bool(vad)
        d.last_seen_at = ts
        d.metrics_count += 1

    def compute_segment_hint(
        self, segment_key: str, center_ts: datetime, window_ms: int | None = None,
    ) -> SegmentSideHint | None:
        """Подсказка стороны для реплики (или None, если уверенности мало/нет устройств)."""
        if not self.enabled:
            return None
        win = window_ms or self.window_ms
        lo = center_ts - timedelta(milliseconds=win)
        hi = center_ts + timedelta(milliseconds=win)
        energy = {"self": 0.0, "opponent": 0.0, "unknown": 0.0}
        max_rms = 0.0
        device_count = 0
        for cid, dq in self.metrics.items():
            d = self.devices.get(cid)
            if d is None or not d.enabled:
                continue
            relevant = [m for m in dq if lo <= m.server_ts <= hi]
            if not relevant:
                continue
            device_count += 1
            e = sum(m.rms for m in relevant)
            peak = max(m.rms for m in relevant)
            max_rms = max(max_rms, peak)
            key = d.side_hint if d.side_hint in ("self", "opponent") else "unknown"
            energy[key] += e
        if device_count == 0:
            return None
        side, confidence, reason = score_segment_side(
            energy["self"], energy["opponent"], energy["unknown"], max_rms,
            min_rms=self.min_rms, ratio=self.ratio, min_confidence=self.min_confidence,
        )
        if side is None:
            return None
        return SegmentSideHint(
            segment_key=segment_key, side=side, confidence=confidence, reason=reason,
            self_energy=energy["self"], opponent_energy=energy["opponent"],
            unknown_energy=energy["unknown"], device_count=device_count, window_ms=win,
        )
