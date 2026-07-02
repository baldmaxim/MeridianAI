"""Safe filtering helpers для canary trace events (Этап 13).

Позволяет резать SOURCE_RECONCILE_TRACE / SIGNAL_ENGINE_TRACE по meeting_id / session_id /
check_id, чтобы не смешивать разные встречи в одном readiness verdict.

Безопасность: raw meeting/session ids НЕ возвращаются списком и НЕ логируются. В stats отдаются
только counts, флаги и хэши фильтр-токенов. Это trace metadata, не transcript data — здесь нет
raw text / speaker labels / source ids / segment ids.
"""

import hashlib
import re
from typing import Any, Optional

_MAX_TOKEN_LEN = 120


def normalize_filter_token(value: Any) -> Optional[str]:
    """Привести фильтр-значение к безопасному строковому токену.

    None/пусто → None; убрать переводы строк и схлопнуть пробелы; обрезать до 120 символов.
    Само значение не логируется.
    """
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value)).strip()
    if not s:
        return None
    return s[:_MAX_TOKEN_LEN]


def hash_filter_token(value: Optional[str]) -> Optional[str]:
    """sha256-хэш (первые 16 символов) от нормализованного токена. None → None."""
    if not value:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _event_field(event: dict, key: str) -> Optional[str]:
    """str-представление id-поля события или None, если поле пустое/отсутствует."""
    if not isinstance(event, dict):
        return None
    v = event.get(key)
    if v is None:
        return None
    s = str(v).strip()
    if not s or s == "None":
        return None
    return s


def filter_trace_events(
    events: list[dict],
    *,
    meeting_id: Any = None,
    session_id: Any = None,
    check_id: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """Оставить только events, совпадающие по заданным id-фильтрам.

    Незаданный фильтр (None) — не применяется. Заданный фильтр требует точного совпадения
    str(event[field]) == str(filter). Events без нужного поля при активном фильтре отсекаются.

    Возвращает (filtered_events, safe_stats). В stats нет raw id — только counts/флаги/хэши.
    """
    m = normalize_filter_token(meeting_id)
    s = normalize_filter_token(session_id)
    c = normalize_filter_token(check_id)

    out: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if m is not None and _event_field(ev, "meeting_id") != m:
            continue
        if s is not None and _event_field(ev, "session_id") != s:
            continue
        if c is not None and _event_field(ev, "check_id") != c:
            continue
        out.append(ev)

    stats = {
        "input_count": len(events),
        "output_count": len(out),
        "filters_applied": {
            "meeting_id": m is not None,
            "session_id": s is not None,
            "check_id": c is not None,
        },
        "filter_hashes": {
            "meeting_id": hash_filter_token(m),
            "session_id": hash_filter_token(s),
            "check_id": hash_filter_token(c),
        },
    }
    return out, stats


def summarize_trace_scope(
    *,
    source_reconcile_events: list[dict],
    signal_engine_events: list[dict],
) -> dict:
    """Безопасный обзор охвата trace: сколько встреч/сессий, есть ли смешение.

    distinct считается по set(str(id)) — но сами id НЕ возвращаются. None для distinct, если
    id вообще отсутствуют. Только trace metadata.
    """
    meetings: set[str] = set()
    sessions: set[str] = set()
    no_meeting = 0
    no_session = 0

    for ev in list(source_reconcile_events) + list(signal_engine_events):
        if not isinstance(ev, dict):
            continue
        mid = _event_field(ev, "meeting_id")
        if mid is None:
            no_meeting += 1
        else:
            meetings.add(mid)
        sid = _event_field(ev, "session_id")
        if sid is None:
            no_session += 1
        else:
            sessions.add(sid)

    return {
        "source_reconcile_event_count": len(source_reconcile_events),
        "signal_engine_event_count": len(signal_engine_events),
        "distinct_meeting_count": len(meetings) if meetings else None,
        "distinct_session_count": len(sessions) if sessions else None,
        "has_mixed_meetings": len(meetings) > 1,
        "has_mixed_sessions": len(sessions) > 1,
        "events_without_meeting_id": no_meeting,
        "events_without_session_id": no_session,
    }
