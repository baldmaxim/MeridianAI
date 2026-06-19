"""Тесты device clock sync (Этап 9.1) — pure NTP-расчёты."""

from app.services.device_clock import (
    ClientClockPing,
    ClockSyncReport,
    aggregate,
    classify_quality,
    ntp_sample,
)


def test_ntp_sample_known_offset_and_rtt():
    # Клиент отстаёт от сервера на +1000 мс, симметричный путь rtt=120.
    # t0(client)=0; путь туда 60 → server_receive в server-времени = 0+1000+60=1060
    # сервер мгновенно отвечает: server_send=1060; путь обратно 60 → t3(client)=0+120=120
    ping = ClientClockPing(seq=1, client_send_ms=0, server_receive_ms=1060,
                           server_send_ms=1060)
    offset, rtt = ntp_sample(ping, client_receive_ms=120)
    assert round(rtt) == 120
    assert round(offset) == 1000


def test_ntp_sample_rtt_clamped_non_negative():
    ping = ClientClockPing(seq=1, client_send_ms=100, server_receive_ms=100,
                           server_send_ms=200)
    _offset, rtt = ntp_sample(ping, client_receive_ms=150)
    assert rtt >= 0.0


def test_classify_quality_thresholds():
    assert classify_quality(10) == "excellent"
    assert classify_quality(79.9) == "excellent"
    assert classify_quality(80) == "good"
    assert classify_quality(199) == "good"
    assert classify_quality(200) == "fair"
    assert classify_quality(499) == "fair"
    assert classify_quality(500) == "poor"
    assert classify_quality(5000) == "poor"


def test_classify_quality_bad_input():
    assert classify_quality(None) == "poor"  # type: ignore[arg-type]


def test_aggregate_empty():
    assert aggregate([]) is None


def test_aggregate_prefers_low_rtt_samples():
    # Выборки с высоким rtt имеют «грязный» offset; агрегат должен взять под-набор
    # с наименьшим rtt и вернуть его медиану.
    samples = [
        (1000.0, 40.0),   # точные
        (1010.0, 50.0),   # точные
        (1005.0, 60.0),   # точные
        (3000.0, 400.0),  # грязные (высокий rtt) — должны быть отброшены
        (5000.0, 800.0),  # грязные
    ]
    report = aggregate(samples)
    assert isinstance(report, ClockSyncReport)
    assert report.samples_count == 5
    # медиана offset лучшей половины (3 из 5) — около 1005, далеко от грязных 3000/5000
    assert 1000.0 <= report.offset_ms <= 1010.0
    assert report.quality == "excellent"  # rtt лучшей половины < 80


def test_aggregate_single_sample():
    report = aggregate([(250.0, 150.0)])
    assert report is not None
    assert report.offset_ms == 250.0
    assert report.rtt_ms == 150.0
    assert report.quality == "good"
    assert report.samples_count == 1
