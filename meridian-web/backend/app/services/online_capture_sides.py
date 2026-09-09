"""Сторона реплики в онлайн-встрече: микрофон = мы, звук встречи = оппонент.

В онлайне сторона говорящего известна почти достоверно: наш голос есть только в микрофоне,
голос второй стороны — только в захвате вкладки/экрана (Zoom/Teams/Meet не возвращают нам
наш же голос). Это куда надёжнее, чем разбирать общий поток диаризацией.

Модуль делает две вещи:
  1. `virtual_device_ids` — два виртуальных «observer-устройства» на одно desktop-соединение,
     чтобы переиспользовать уже существующий и протестированный расчёт стороны реплики
     (ObserverDiarization.compute_segment_hint) без нового протокола.
  2. `OnlineCaptureSideVoter` — копит подсказки по каждой метке спикера и, когда набралась
     уверенность, один раз отдаёт сторону для авто-назначения. Ручное назначение
     пользователя всегда главнее: вызывающий не отдаёт сюда уже назначенные вручную метки.

Чистый модуль: без БД, без IO, без времени — всё приходит аргументами.
"""

from dataclasses import dataclass, field

# Суффиксы виртуальных устройств одного соединения (см. virtual_device_ids).
SELF_DEVICE_SUFFIX = "#mic"
OPPONENT_DEVICE_SUFFIX = "#meeting"

# Метка источника подсказки в WS-событии segment_side_hint.
HINT_SOURCE = "online_capture"


def virtual_device_ids(connection_id: str) -> tuple[str, str]:
    """(id устройства «мы», id устройства «оппонент») для одного desktop-соединения."""
    return f"{connection_id}{SELF_DEVICE_SUFFIX}", f"{connection_id}{OPPONENT_DEVICE_SUFFIX}"


def clamp_level(value) -> float:
    """Уровень 0..1 из недоверенного JSON. Мусор/NaN/отрицательное → 0.0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return max(0.0, min(1.0, f))


@dataclass
class _SpeakerVotes:
    self_weight: float = 0.0
    opponent_weight: float = 0.0

    @property
    def total(self) -> float:
        return self.self_weight + self.opponent_weight


@dataclass
class OnlineCaptureSideVoter:
    """Копит подсказки стороны по меткам спикеров и решает, когда назначать сторону.

    min_votes    — минимум подсказок по спикеру до первого решения;
    min_ratio    — какая доля веса должна приходиться на одну сторону (0..1);
    Возврат `record()` — сторона для назначения или None (ещё рано / уже назначено).
    """

    min_votes: int = 3
    min_ratio: float = 0.75
    votes: dict[str, _SpeakerVotes] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    assigned: dict[str, str] = field(default_factory=dict)

    def record(self, speaker_label: str, side: str, confidence: float = 1.0) -> str | None:
        label = (speaker_label or "").strip()
        if not label or side not in ("self", "opponent"):
            return None
        weight = clamp_level(confidence) or 1.0
        v = self.votes.setdefault(label, _SpeakerVotes())
        if side == "self":
            v.self_weight += weight
        else:
            v.opponent_weight += weight
        self.counts[label] = self.counts.get(label, 0) + 1

        if self.counts[label] < self.min_votes or v.total <= 0:
            return None
        dominant = "self" if v.self_weight >= v.opponent_weight else "opponent"
        share = max(v.self_weight, v.opponent_weight) / v.total
        if share < self.min_ratio:
            return None
        if self.assigned.get(label) == dominant:
            return None  # уже назначено — не дёргаем БД и UI повторно
        self.assigned[label] = dominant
        return dominant

    def is_auto_assigned(self, speaker_label: str) -> bool:
        """Назначал ли сторону этой метки именно авто-режим (а не пользователь)."""
        return (speaker_label or "").strip() in self.assigned

    def forget(self, speaker_label: str) -> None:
        """Забыть авто-решение (пользователь исправил сторону вручную — он главнее)."""
        label = (speaker_label or "").strip()
        self.assigned.pop(label, None)
        self.votes.pop(label, None)
        self.counts.pop(label, None)

    def reset(self) -> None:
        self.votes.clear()
        self.counts.clear()
        self.assigned.clear()
