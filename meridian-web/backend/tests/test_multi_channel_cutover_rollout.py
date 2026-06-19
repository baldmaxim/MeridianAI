"""Canary rollout gating cutover (Этап 9.8)."""

from app.services.multi_channel_cutover_rollout import (
    evaluate_cutover_rollout, meeting_rollout_bucket,
)


def ev(meeting_id, **over):
    kw = dict(meeting_id=meeting_id, owner_user_id=10, enabled=True, rollout_percent=0,
              allowlist_user_ids=set(), allowlist_meeting_ids=set())
    kw.update(over)
    return evaluate_cutover_rollout(**kw)


def test_disabled_always_denied():
    d = ev(1, enabled=False, rollout_percent=100, allowlist_meeting_ids={1})
    assert d.allowed is False and d.reason == "feature_disabled"


def test_bucket_is_deterministic_and_in_range():
    b1 = meeting_rollout_bucket(42)
    b2 = meeting_rollout_bucket(42)
    assert b1 == b2 and 0 <= b1 < 100


def test_zero_percent_denied_without_allowlist():
    d = ev(7, rollout_percent=0)
    assert d.allowed is False and d.reason == "not_in_rollout"


def test_full_percent_allows_all():
    d = ev(123456, rollout_percent=100)
    assert d.allowed is True and d.reason == "rollout_full"


def test_allowlist_meeting_overrides_percent():
    d = ev(5, rollout_percent=0, allowlist_meeting_ids={5})
    assert d.allowed is True and d.reason == "allowlist_meeting"


def test_allowlist_user_overrides_percent():
    d = ev(5, owner_user_id=99, rollout_percent=0, allowlist_user_ids={99})
    assert d.allowed is True and d.reason == "allowlist_user"


def test_bucket_boundary_inclusion():
    # выбрать meeting, у которого bucket известен, и проверить порог bucket<pct
    mid = 0
    bucket = meeting_rollout_bucket(mid)
    just_below = ev(mid, rollout_percent=bucket)        # pct == bucket → bucket<pct False
    just_above = ev(mid, rollout_percent=bucket + 1)    # bucket<pct True
    assert just_below.allowed is False
    assert just_above.allowed is True and just_above.reason == "rollout_bucket"


def test_none_owner_without_allowlist_user():
    d = ev(3, owner_user_id=None, rollout_percent=0, allowlist_user_ids={1, 2})
    assert d.allowed is False
