"""Тесты observer-диаризации v1 (Этап 9) — pure scoring + буфер метрик."""

from datetime import datetime, timedelta

from app.config import get_settings
from app.services.observer_diarization import ObserverDiarization, score_segment_side


def test_score_clear_self():
    side, conf, reason = score_segment_side(
        self_energy=10.0, opponent_energy=1.0, unknown_energy=0.0, max_rms=0.2,
        min_rms=0.025, ratio=1.35, min_confidence=0.65,
    )
    assert side == "self"
    assert reason == "level_ratio"
    assert conf >= 0.65


def test_score_clear_opponent():
    side, _conf, _ = score_segment_side(
        self_energy=1.0, opponent_energy=12.0, unknown_energy=0.0, max_rms=0.3,
        min_rms=0.025, ratio=1.35, min_confidence=0.65,
    )
    assert side == "opponent"


def test_score_too_quiet():
    side, _conf, reason = score_segment_side(
        self_energy=10.0, opponent_energy=0.0, unknown_energy=0.0, max_rms=0.001,
        min_rms=0.025, ratio=1.35, min_confidence=0.65,
    )
    assert side is None
    assert reason == "too_quiet"


def test_score_low_confidence_when_close():
    side, _conf, reason = score_segment_side(
        self_energy=10.0, opponent_energy=9.5, unknown_energy=0.0, max_rms=0.2,
        min_rms=0.025, ratio=1.35, min_confidence=0.65,
    )
    assert side is None
    assert reason == "low_confidence"


def _buffer():
    return ObserverDiarization(get_settings())


def test_buffer_hint_self_louder():
    obs = _buffer()
    obs.register_device("c_self", 1, "observer", side_hint="self")
    obs.register_device("c_opp", 2, "observer", side_hint="opponent")
    center = datetime(2026, 1, 1, 12, 0, 0)
    # рядом с нами громко, у другой стороны тихо
    for i in range(5):
        ts = center + timedelta(milliseconds=i * 100)
        obs.add_metric("c_self", rms=0.3, server_ts=ts)
        obs.add_metric("c_opp", rms=0.02, server_ts=ts)
    hint = obs.compute_segment_hint("seg1", center)
    assert hint is not None
    assert hint.side == "self"
    assert hint.device_count == 2
    assert hint.confidence >= 0.65


def test_buffer_no_devices_no_hint():
    obs = _buffer()
    assert obs.compute_segment_hint("seg1", datetime(2026, 1, 1, 12, 0, 0)) is None


def test_buffer_outside_window_ignored():
    obs = _buffer()
    obs.register_device("c_self", 1, "observer", side_hint="self")
    center = datetime(2026, 1, 1, 12, 0, 0)
    # метрика далеко за окном (+10s)
    obs.add_metric("c_self", rms=0.5, server_ts=center + timedelta(seconds=10))
    assert obs.compute_segment_hint("seg1", center) is None


def test_set_side_hint_and_remove():
    obs = _buffer()
    obs.register_device("c1", 1, "observer", side_hint=None)
    obs.set_side_hint("c1", "we")  # alias → self
    assert obs.devices["c1"].side_hint == "self"
    obs.remove_device("c1")
    assert "c1" not in obs.devices and "c1" not in obs.metrics


def test_auto_apply_off_by_default():
    obs = _buffer()
    assert obs.auto_apply is False  # MVP: auto-apply выключен
