"""Safe trace filtering (Этап 13)."""

import json

from app.core.context.canary_trace_filter import (
    filter_trace_events,
    hash_filter_token,
    normalize_filter_token,
    summarize_trace_scope,
)


def _ev(meeting_id=None, session_id=None, check_id="chk", match_reason="matched"):
    e = {"check_id": check_id, "match_reason": match_reason}
    if meeting_id is not None:
        e["meeting_id"] = meeting_id
    if session_id is not None:
        e["session_id"] = session_id
    return e


def test_normalize_filter_token():
    assert normalize_filter_token("  42 ") == "42"
    assert normalize_filter_token("") is None
    assert normalize_filter_token("   ") is None
    assert normalize_filter_token(None) is None
    assert normalize_filter_token(123) == "123"
    assert normalize_filter_token("a\nb") == "a b"
    assert len(normalize_filter_token("x" * 500)) == 120


def test_hash_filter_token():
    assert hash_filter_token(None) is None
    assert hash_filter_token("") is None
    h = hash_filter_token("42")
    assert isinstance(h, str) and 12 <= len(h) <= 16
    assert hash_filter_token("42") == hash_filter_token("42")  # стабильный
    assert hash_filter_token("42") != "42"  # это хэш, не сырой id


def test_filter_by_meeting_id():
    events = [_ev(meeting_id="42"), _ev(meeting_id="99"), _ev(meeting_id=42)]
    out, stats = filter_trace_events(events, meeting_id="42")
    assert len(out) == 2  # "42" и int 42
    assert stats["input_count"] == 3
    assert stats["output_count"] == 2
    assert stats["filters_applied"]["meeting_id"] is True
    assert stats["filters_applied"]["session_id"] is False


def test_filter_by_session_id():
    events = [_ev(session_id="s1"), _ev(session_id="s2"), _ev(session_id="s1")]
    out, stats = filter_trace_events(events, session_id="s1")
    assert len(out) == 2
    assert stats["filters_applied"]["session_id"] is True


def test_filter_by_check_id():
    events = [_ev(check_id="A"), _ev(check_id="B")]
    out, _ = filter_trace_events(events, check_id="A")
    assert len(out) == 1
    assert out[0]["check_id"] == "A"


def test_filter_excludes_events_without_id():
    events = [_ev(meeting_id="42"), _ev()]  # второй без meeting_id
    out, _ = filter_trace_events(events, meeting_id="42")
    assert len(out) == 1


def test_filter_stats_have_hashes_not_raw_ids():
    events = [_ev(meeting_id="secret-meet-42", session_id="secret-sess-7")]
    _, stats = filter_trace_events(events, meeting_id="secret-meet-42", session_id="secret-sess-7")
    blob = json.dumps(stats, ensure_ascii=False)
    # сырые id не должны попадать в stats — только хэши
    assert "secret-meet-42" not in blob
    assert "secret-sess-7" not in blob
    assert stats["filter_hashes"]["meeting_id"] is not None
    assert stats["filter_hashes"]["session_id"] is not None
    assert stats["filter_hashes"]["check_id"] is None


def test_summarize_trace_scope_mixed():
    sr = [_ev(meeting_id="1", session_id="s1"), _ev(meeting_id="2", session_id="s2")]
    se = [_ev(meeting_id="1", session_id="s1")]
    scope = summarize_trace_scope(source_reconcile_events=sr, signal_engine_events=se)
    assert scope["source_reconcile_event_count"] == 2
    assert scope["signal_engine_event_count"] == 1
    assert scope["distinct_meeting_count"] == 2
    assert scope["distinct_session_count"] == 2
    assert scope["has_mixed_meetings"] is True
    assert scope["has_mixed_sessions"] is True


def test_summarize_trace_scope_single():
    sr = [_ev(meeting_id="42", session_id="s1"), _ev(meeting_id="42", session_id="s1")]
    scope = summarize_trace_scope(source_reconcile_events=sr, signal_engine_events=[])
    assert scope["distinct_meeting_count"] == 1
    assert scope["has_mixed_meetings"] is False


def test_summarize_counts_events_without_ids():
    sr = [_ev(), _ev(meeting_id="42")]
    scope = summarize_trace_scope(source_reconcile_events=sr, signal_engine_events=[])
    assert scope["events_without_meeting_id"] == 1
    assert scope["events_without_session_id"] == 2
    assert scope["distinct_session_count"] is None  # ни у кого нет session_id


def test_summarize_no_raw_id_list_in_output():
    sr = [_ev(meeting_id="raw-meet-xyz", session_id="raw-sess-abc")]
    scope = summarize_trace_scope(source_reconcile_events=sr, signal_engine_events=[])
    blob = json.dumps(scope, ensure_ascii=False)
    assert "raw-meet-xyz" not in blob
    assert "raw-sess-abc" not in blob
