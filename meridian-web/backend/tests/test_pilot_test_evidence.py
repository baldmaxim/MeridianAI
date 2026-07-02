"""Этап 27: test evidence helper — сборка + разбор pytest summary."""

from app.core.pilot.test_evidence import (
    build_test_evidence_from_summary, parse_pytest_summary_text,
)


def test_build_evidence():
    ev = build_test_evidence_from_summary(backend_passed=1197, backend_failed=0, frontend_build="passed")
    assert ev["backend"] == {"passed": 1197, "failed": 0}
    assert ev["frontend"]["build"] == "passed"
    assert ev["known_failures"] == []


def test_parse_pytest_passed():
    ev = parse_pytest_summary_text("1197 passed, 2 warnings in 842.00s (0:14:01)")
    assert ev["backend"]["passed"] == 1197 and ev["backend"]["failed"] == 0


def test_parse_pytest_with_failures():
    ev = parse_pytest_summary_text("2 failed, 1194 passed, 2 warnings in 800s")
    assert ev["backend"]["passed"] == 1194 and ev["backend"]["failed"] == 2


def test_parse_pytest_errors_count_as_failed():
    ev = parse_pytest_summary_text("10 passed, 1 error in 5s")
    assert ev["backend"]["failed"] == 1


def test_parse_empty():
    ev = parse_pytest_summary_text("")
    assert ev["backend"] == {"passed": 0, "failed": 0}
