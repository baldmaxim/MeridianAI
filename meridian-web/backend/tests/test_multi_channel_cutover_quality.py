"""Quality gate cutover (Этап 9.8)."""

from app.services.multi_channel_cutover_quality import evaluate_cutover_quality


def q(**over):
    kw = dict(
        live_status="streaming", channel_count=2, min_channels=2,
        final_segment_count=10, min_final_segments=5,
        secondary_silence_ratios=[0.1], max_secondary_silence_ratio=0.7,
        channel_clock_quality={0: "good", 1: "good"},
        reconciliation_matched=8, reconciliation_total=10, min_match_ratio=0.5,
    )
    kw.update(over)
    return evaluate_cutover_quality(**kw)


def test_healthy_passes():
    r = q()
    assert r.ok is True and not r.reasons and 0.0 <= r.score <= 1.0


def test_live_not_streaming_fails():
    r = q(live_status="idle")
    assert r.ok is False and "live_not_streaming" in r.reasons


def test_too_few_channels():
    r = q(channel_count=1)
    assert "too_few_channels" in r.reasons


def test_too_few_final_segments():
    r = q(final_segment_count=2)
    assert r.ok is False and "too_few_final_segments" in r.reasons


def test_secondary_too_silent():
    r = q(secondary_silence_ratios=[0.9])
    assert "secondary_too_silent" in r.reasons


def test_poor_clock_quality():
    r = q(channel_clock_quality={0: "good", 1: "poor"})
    assert "poor_clock_quality" in r.reasons
    r2 = q(channel_clock_quality={0: "good", 1: None})
    assert "poor_clock_quality" in r2.reasons


def test_low_match_ratio():
    r = q(reconciliation_matched=2, reconciliation_total=10, min_match_ratio=0.5)
    assert "low_match_ratio" in r.reasons


def test_no_reconciliation_data_does_not_penalize_match():
    # total=0 → match_ratio неизвестен, не штрафуем
    r = q(reconciliation_matched=0, reconciliation_total=0)
    assert "low_match_ratio" not in r.reasons


def test_degraded_is_acceptable_live_status():
    r = q(live_status="degraded")
    assert "live_not_streaming" not in r.reasons


def test_score_drops_with_problems():
    good = q().score
    bad = q(live_status="idle", final_segment_count=0, secondary_silence_ratios=[1.0],
            channel_clock_quality={0: "poor"}, reconciliation_matched=0, reconciliation_total=10).score
    assert bad < good
