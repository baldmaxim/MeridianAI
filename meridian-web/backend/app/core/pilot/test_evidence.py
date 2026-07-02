"""Test evidence helper (Этап 27).

Компактное safe-представление результатов тестов для pilot readiness (без парсинга огромных
pytest-логов). Поддерживает ручной JSON и простой разбор pytest summary-строки.
"""

import re

_RE_PASSED = re.compile(r"(\d+)\s+passed")
_RE_FAILED = re.compile(r"(\d+)\s+failed")
_RE_ERROR = re.compile(r"(\d+)\s+error")


def build_test_evidence_from_summary(*, backend_passed: int = 0, backend_failed: int = 0,
                                     frontend_build: str = "unknown",
                                     known_failures: list[str] | None = None) -> dict:
    return {
        "backend": {"passed": int(backend_passed), "failed": int(backend_failed)},
        "frontend": {"build": frontend_build},
        "known_failures": list(known_failures or []),
    }


def parse_pytest_summary_text(text: str) -> dict:
    """Достать passed/failed из хвоста pytest (напр. '1197 passed, 2 warnings'). Без raw-логов."""
    t = text or ""
    passed = int(_RE_PASSED.search(t).group(1)) if _RE_PASSED.search(t) else 0
    failed = int(_RE_FAILED.search(t).group(1)) if _RE_FAILED.search(t) else 0
    errors = int(_RE_ERROR.search(t).group(1)) if _RE_ERROR.search(t) else 0
    return {
        "backend": {"passed": passed, "failed": failed + errors},
        "frontend": {"build": "unknown"},
        "known_failures": [],
    }
