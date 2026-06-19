"""Device clock sync (Этап 9.1) — pure-сервис единой server timeline.

Несколько устройств одной встречи (desktop-рекордер + observer-телефон) имеют
расходящиеся системные часы. Чтобы позже склеивать каналы по времени, каждый клиент
синхронизирует часы с backend по NTP-подобной схеме ping/pong, а backend хранит
полученный offset/RTT на соединении.

Схема (вариант «клиент считает, сервер хранит»):
  t0 = client_send_ms     (клиент отправил clock_ping)
  t1 = server_receive_ms  (сервер принял ping)
  t2 = server_send_ms     (сервер отправил clock_pong)
  t3 = client_receive_ms  (клиент принял pong)

  rtt    = (t3 - t0) - (t2 - t1)
  offset = ((t1 - t0) + (t2 - t3)) / 2     # client_clock + offset ≈ server_clock

Этот модуль чистый: без I/O и без обращения к системным часам внутри расчётов
(всё через аргументы) — поэтому легко тестируется и переиспользуется на обеих сторонах.
"""

from dataclasses import dataclass
from datetime import datetime
from statistics import median


# Пороги качества по RTT (мс). Меньший RTT → точнее offset.
QUALITY_EXCELLENT_MS = 80.0
QUALITY_GOOD_MS = 200.0
QUALITY_FAIR_MS = 500.0

VALID_QUALITIES = ("excellent", "good", "fair", "poor")


@dataclass
class ClockSyncReport:
    offset_ms: float
    rtt_ms: float
    quality: str
    samples_count: int = 1
    updated_at: datetime | None = None


@dataclass
class ClientClockPing:
    seq: int
    client_send_ms: int
    server_receive_ms: int
    server_send_ms: int


def ntp_sample(ping: ClientClockPing, client_receive_ms: int) -> tuple[float, float]:
    """Вернуть (offset_ms, rtt_ms) по одной выборке ping/pong (формула NTP).

    rtt не может быть отрицательным — клампим к 0.
    """
    t0 = ping.client_send_ms
    t1 = ping.server_receive_ms
    t2 = ping.server_send_ms
    t3 = client_receive_ms
    rtt = (t3 - t0) - (t2 - t1)
    offset = ((t1 - t0) + (t2 - t3)) / 2.0
    return float(offset), max(0.0, float(rtt))


def classify_quality(rtt_ms: float) -> str:
    """Категория качества синхронизации по RTT."""
    try:
        r = float(rtt_ms)
    except (TypeError, ValueError):
        return "poor"
    if r < QUALITY_EXCELLENT_MS:
        return "excellent"
    if r < QUALITY_GOOD_MS:
        return "good"
    if r < QUALITY_FAIR_MS:
        return "fair"
    return "poor"


def normalize_quality(quality: str | None, rtt_ms: float) -> str:
    """Не доверять клиентскому ярлыку: всегда пересчитываем quality от rtt."""
    return classify_quality(rtt_ms)


def aggregate(samples: list[tuple[float, float]]) -> ClockSyncReport | None:
    """Свести список выборок (offset_ms, rtt_ms) в один отчёт.

    Классика NTP: берём под-набор выборок с наименьшим RTT (наиболее точные),
    итоговый offset — медиана offset этого под-набора, rtt — медиана их rtt.
    Возвращает None, если выборок нет.
    """
    if not samples:
        return None
    # отсортировать по rtt и взять лучшую половину (минимум 1)
    ordered = sorted(samples, key=lambda s: s[1])
    keep = max(1, len(ordered) // 2)
    best = ordered[:keep]
    offset = float(median(s[0] for s in best))
    rtt = float(median(s[1] for s in best))
    return ClockSyncReport(
        offset_ms=offset,
        rtt_ms=rtt,
        quality=classify_quality(rtt),
        samples_count=len(samples),
    )
