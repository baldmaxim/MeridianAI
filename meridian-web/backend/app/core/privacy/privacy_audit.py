"""Safe privacy/retention audit logging (Этап 25).

Логирует ТОЛЬКО метаданные события: тип, meeting_id/user_id (как id, проект и так логирует id),
counts по категориям, warnings. НИКОГДА: raw transcript/audio/document text, filename, S3 key,
presigned URL, API keys, списки speaker labels.
"""

import logging

_ALLOWED_EVENTS = {
    "privacy_inventory_viewed",
    "privacy_export_created",
    "privacy_delete_plan_created",
    "privacy_delete_executed",
    "retention_cleanup_dry_run",
    "retention_cleanup_executed",
}


def _safe_counts(counts) -> dict:
    """Оставить только числовые counts (category -> int). Никаких строк/значений."""
    out: dict[str, int] = {}
    if isinstance(counts, dict):
        for k, v in counts.items():
            try:
                out[str(k)[:40]] = int(v)
            except (TypeError, ValueError):
                continue
    return out


def log_privacy_event(logger: logging.Logger, event_type: str, *, meeting_id=None,
                      user_id=None, counts=None, warnings=None) -> None:
    """Безопасно залогировать privacy-событие (counts-only)."""
    ev = event_type if event_type in _ALLOWED_EVENTS else "privacy_unknown_event"
    warn_n = len(warnings) if isinstance(warnings, (list, tuple)) else 0
    logger.info("[Privacy] event=%s meeting_id=%s user_id=%s counts=%s warnings=%d",
                ev, meeting_id, user_id, _safe_counts(counts), warn_n)
