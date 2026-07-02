"""Этап 26: privacy log analyzer — парс безопасных событий, маскировка вредоносных raw-строк."""

import json

from app.core.privacy.privacy_log_analysis import (
    analyze_privacy_lines, extract_privacy_event_from_line,
)

INV = ("2026-07-01 INFO meridian.privacy [Privacy] event=privacy_inventory_viewed "
       "meeting_id=5 user_id=7 counts={'transcript': 3} warnings=1")
PLAN = "... [Privacy] event=privacy_delete_plan_created meeting_id=5 user_id=7 counts={} warnings=1"
EXEC = "... [Privacy] event=privacy_delete_executed meeting_id=5 user_id=7 counts={'transcript': 3} warnings=0"
RET_DRY = "... [Privacy] event=retention_cleanup_dry_run meeting_id=None user_id=None counts={} warnings=1"
RET_EXE = "... [Privacy] event=retention_cleanup_executed meeting_id=None user_id=None counts={} warnings=0"
MALICIOUS = ("... [Privacy] event=privacy_export_created meeting_id=5 user_id=7 counts={} warnings=0 "
             "https://bucket.s3/doc?X-Amz-Signature=LEAKSIG secretname.pdf секретный_текст")


def test_extract_event():
    assert extract_privacy_event_from_line(INV) == {"event": "privacy_inventory_viewed", "warnings": 1}


def test_extract_ignores_non_privacy():
    assert extract_privacy_event_from_line("random log line") is None


def test_analyze_summary():
    s = analyze_privacy_lines([INV, PLAN, EXEC, RET_DRY, RET_EXE])
    assert s["total"] == 5
    assert s["delete_plan_count"] == 1
    assert s["delete_executed_count"] == 1
    assert s["retention_dry_run_count"] == 1
    assert s["retention_executed_count"] == 1
    assert s["by_event_type"]["privacy_inventory_viewed"] == 1
    assert "hard_delete_executed_events_present" in s["notes"]


def test_malicious_raw_not_echoed():
    s = analyze_privacy_lines([MALICIOUS])
    blob = json.dumps(s, ensure_ascii=False)
    for leak in ("LEAKSIG", "X-Amz", "secretname.pdf", "секретный_текст", "bucket.s3"):
        assert leak not in blob
    assert s["by_event_type"]["privacy_export_created"] == 1  # событие всё равно распознано


def test_no_events():
    s = analyze_privacy_lines(["nothing here", ""])
    assert s["total"] == 0 and "no_privacy_events_found" in s["notes"]
