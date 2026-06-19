"""Quality gate продвижения на multi-channel transcript (Этап 9.8) — чистые функции.

Оценивает ГОТОВНОСТЬ live multi-channel сессии быть авторитетным источником. Гейтит
ручной promote (если включён require_quality_gate и не передан force). НЕ выполняет
авто-fallback по качеству — авто-fallback только при ЖЁСТКОМ сбое live (отдельная логика).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CutoverQualityReport:
    ok: bool
    score: float                 # 0..1, грубая уверенность (для UI/метрик)
    reasons: tuple[str, ...]     # причины НЕготовности (пусто если ok)
    metrics: dict

    def to_dict(self) -> dict:
        return {"ok": self.ok, "score": self.score,
                "reasons": list(self.reasons), "metrics": dict(self.metrics)}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def evaluate_cutover_quality(
    *,
    live_status: str,
    channel_count: int,
    min_channels: int,
    final_segment_count: int,
    min_final_segments: int,
    secondary_silence_ratios: list[float],
    max_secondary_silence_ratio: float,
    channel_clock_quality: dict,
    reconciliation_matched: int,
    reconciliation_total: int,
    min_match_ratio: float,
) -> CutoverQualityReport:
    reasons: list[str] = []

    if live_status not in ("streaming", "degraded"):
        reasons.append("live_not_streaming")
    if channel_count < max(2, min_channels):
        reasons.append("too_few_channels")
    if final_segment_count < max(0, min_final_segments):
        reasons.append("too_few_final_segments")

    worst_silence = max(secondary_silence_ratios, default=0.0)
    if worst_silence > max_secondary_silence_ratio:
        reasons.append("secondary_too_silent")

    poor_clock = any(q in (None, "poor") for q in (channel_clock_quality or {}).values())
    if poor_clock:
        reasons.append("poor_clock_quality")

    match_ratio = (reconciliation_matched / reconciliation_total) if reconciliation_total > 0 else None
    if match_ratio is not None and match_ratio < min_match_ratio:
        reasons.append("low_match_ratio")

    # score (advisory): взвешенная смесь под-метрик
    silence_score = 1.0 - _clamp01(worst_silence)
    seg_score = _clamp01(final_segment_count / max(1, min_final_segments)) if min_final_segments else 1.0
    match_component = _clamp01(match_ratio) if match_ratio is not None else 1.0
    clock_score = 0.0 if poor_clock else 1.0
    live_score = 1.0 if live_status in ("streaming", "degraded") else 0.0
    score = round(
        0.30 * match_component + 0.25 * silence_score + 0.20 * seg_score
        + 0.15 * clock_score + 0.10 * live_score,
        3,
    )

    metrics = {
        "live_status": live_status,
        "channel_count": channel_count,
        "final_segment_count": final_segment_count,
        "worst_secondary_silence_ratio": round(worst_silence, 3),
        "poor_clock_quality": poor_clock,
        "match_ratio": round(match_ratio, 3) if match_ratio is not None else None,
        "reconciliation_matched": reconciliation_matched,
        "reconciliation_total": reconciliation_total,
    }
    return CutoverQualityReport(ok=not reasons, score=score,
                                reasons=tuple(reasons), metrics=metrics)
