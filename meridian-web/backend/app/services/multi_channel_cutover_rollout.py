"""Canary rollout gating для production cutover (Этап 9.8) — чистые функции, без I/O.

Решает, ДОСТУПНО ли ручное продвижение конкретной встречи на multi-channel transcript.
НЕ выполняет авто-promote. Детерминированный bucket по meeting_id (стабильный между
рестартами и без Date/random). По умолчанию выключено (enabled=False) → всегда запрещено.
"""

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class RolloutDecision:
    allowed: bool
    # feature_disabled | allowlist_meeting | allowlist_user | rollout_full | rollout_bucket | not_in_rollout
    reason: str
    bucket: int  # 0..99 — детерминированный «слот» встречи


def meeting_rollout_bucket(meeting_id: int) -> int:
    """Стабильный bucket 0..99 для встречи (sha1, без рандома/времени)."""
    digest = hashlib.sha1(f"meridian-cutover:{int(meeting_id)}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def evaluate_cutover_rollout(
    *,
    meeting_id: int,
    owner_user_id: int | None,
    enabled: bool,
    rollout_percent: int,
    allowlist_user_ids: set[int],
    allowlist_meeting_ids: set[int],
) -> RolloutDecision:
    """Доступность cutover для встречи. Allowlist приоритетнее процента; процент по bucket."""
    bucket = meeting_rollout_bucket(meeting_id)
    if not enabled:
        return RolloutDecision(False, "feature_disabled", bucket)
    if meeting_id in (allowlist_meeting_ids or set()):
        return RolloutDecision(True, "allowlist_meeting", bucket)
    if owner_user_id is not None and owner_user_id in (allowlist_user_ids or set()):
        return RolloutDecision(True, "allowlist_user", bucket)
    pct = max(0, min(100, int(rollout_percent)))
    if pct <= 0:
        return RolloutDecision(False, "not_in_rollout", bucket)
    if pct >= 100:
        return RolloutDecision(True, "rollout_full", bucket)
    if bucket < pct:
        return RolloutDecision(True, "rollout_bucket", bucket)
    return RolloutDecision(False, "not_in_rollout", bucket)
