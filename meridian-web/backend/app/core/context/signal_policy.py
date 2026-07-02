"""Signal Engine policy (Этап 2): gating/threshold-решение и resolve runtime-конфига.

Выносит из SessionManager всё решение «показывать/молчать/legacy» в чистые функции,
которые легко тестировать. Не делает побочных эффектов и не зовёт LLM.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel

from .signal_engine import NegotiationSignal, SignalEngineResult

# error_kind, который считаем техническим сбоем (можно отдать legacy fallback)
_TECHNICAL_ERRORS = {"llm_unavailable", "timeout", "exception"}
# error_kind, который считаем проблемой качества ответа модели (НЕ legacy → молчим)
_MODEL_OUTPUT_ERRORS = {"invalid_json", "validation_error"}

_MISSING = object()


class SignalRuntimeConfig(BaseModel):
    enabled: bool
    shadow_mode: bool
    allow_legacy_fallback: bool
    min_confidence: float
    min_actionability: float
    min_urgency: float
    trace_enabled: bool = True
    trace_include_text: bool = False
    trace_sample_rate: float = 1.0
    llm_timeout_seconds: float = 8.0
    # Диагностика: какие signal_engine_* session overrides реально применились.
    # НЕ использовать в decision logic — только для трассировки/тестов.
    overrides_applied: dict = {}


class SignalDecision(BaseModel):
    actual_should_prompt: bool
    would_prompt_without_shadow: bool
    reason: Literal[
        "disabled",
        "shadow_mode",
        "technical_error_legacy_allowed",
        "technical_error_no_legacy",
        "model_output_invalid",
        "should_prompt_false",
        "low_confidence",
        "low_actionability",
        "low_urgency",
        "allowed",
    ]
    legacy_fallback_allowed: bool
    cooldown_key: Optional[str] = None
    score: float
    threshold_summary: dict


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _compute_score(signal: NegotiationSignal) -> float:
    """Простая полезная метрика силы сигнала, clamp 0..1."""
    raw = signal.confidence * signal.actionability * max(signal.urgency, 0.1)
    return _clamp01(raw)


def evaluate_signal_decision(
    signal: NegotiationSignal,
    result: SignalEngineResult,
    config: SignalRuntimeConfig,
) -> SignalDecision:
    """Чистое решение по сигналу. Учитывает enabled, тип ошибки, пороги и shadow."""
    score = _compute_score(signal)
    threshold_summary = {
        "min_confidence": config.min_confidence,
        "min_actionability": config.min_actionability,
        "min_urgency": config.min_urgency,
        "confidence": signal.confidence,
        "actionability": signal.actionability,
        "urgency": signal.urgency,
    }

    def _d(actual, would, reason, legacy, cooldown_key=None):
        return SignalDecision(
            actual_should_prompt=actual,
            would_prompt_without_shadow=would,
            reason=reason,
            legacy_fallback_allowed=legacy,
            cooldown_key=cooldown_key,
            score=score,
            threshold_summary=threshold_summary,
        )

    if not config.enabled:
        return _d(False, False, "disabled", False)

    ek = result.error_kind
    if ek in _TECHNICAL_ERRORS:
        if config.allow_legacy_fallback:
            return _d(False, False, "technical_error_legacy_allowed", True)
        return _d(False, False, "technical_error_no_legacy", False)

    if ek in _MODEL_OUTPUT_ERRORS:
        return _d(False, False, "model_output_invalid", False)

    if not signal.should_prompt:
        return _d(False, False, "should_prompt_false", False)

    if signal.confidence < config.min_confidence:
        return _d(False, False, "low_confidence", False)
    if signal.actionability < config.min_actionability:
        return _d(False, False, "low_actionability", False)
    if signal.urgency < config.min_urgency:
        return _d(False, False, "low_urgency", False)

    # Сильный сигнал прошёл пороги
    cooldown_key = f"signal:{signal.novelty_key}"
    if config.shadow_mode:
        return _d(False, True, "shadow_mode", False, cooldown_key)
    return _d(True, True, "allowed", False, cooldown_key)


# --------------------------------------------------------------------------
# Resolve runtime config: глобальные настройки + per-session/canary override
# --------------------------------------------------------------------------

def _session_get(session_ai: Any, key: str):
    """Достать override-значение из session_ai (dict или объект с атрибутами)."""
    if session_ai is None:
        return _MISSING
    if isinstance(session_ai, dict):
        val = session_ai.get(key, _MISSING)
    else:
        val = getattr(session_ai, key, _MISSING)
    return _MISSING if val is None else val


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def resolve_signal_runtime_config(global_settings, session_ai: Any = None) -> SignalRuntimeConfig:
    """Собрать SignalRuntimeConfig из глобального config + опциональных session overrides.

    session_ai может быть dict или объектом с атрибутами; его signal_engine_* ключи имеют
    приоритет, НО только если глобально разрешены overrides. trace_include_text через session
    override применяется лишь при явном глобальном разрешении (безопасность).
    sample_rate clamp 0..1; timeout clamp 1..60 (<=0 → дефолт 8.0).
    """
    g = global_settings
    overrides_enabled = bool(getattr(g, "ai_signal_engine_session_overrides_enabled", True))
    trace_text_allowed = bool(getattr(g, "ai_signal_engine_session_trace_text_override_allowed", False))
    applied: dict = {}

    def pick(key: str, default, *, allow: bool = True):
        # override применяется только если: overrides_enabled, разрешено для ключа,
        # значение реально передано (не None / не отсутствует).
        if not (overrides_enabled and allow):
            applied[key] = False
            return default
        val = _session_get(session_ai, key)
        if val is _MISSING:
            applied[key] = False
            return default
        applied[key] = True
        return val

    enabled = pick("signal_engine_enabled", g.ai_signal_engine_enabled)
    shadow = pick("signal_engine_shadow_mode", g.ai_signal_engine_shadow_mode)
    allow_legacy = pick("signal_engine_allow_legacy_fallback", g.ai_signal_engine_allow_legacy_fallback)
    min_conf = pick("signal_engine_min_confidence", g.ai_signal_engine_min_confidence)
    min_act = pick("signal_engine_min_actionability", g.ai_signal_engine_min_actionability)
    min_urg = pick("signal_engine_min_urgency", g.ai_signal_engine_min_urgency)
    trace_enabled = pick("signal_engine_trace_enabled", g.ai_signal_engine_trace_enabled)
    # Текст-превью в trace через session override — только при глобальном разрешении.
    trace_include_text = pick("signal_engine_trace_include_text",
                              g.ai_signal_engine_trace_include_text, allow=trace_text_allowed)
    sample_rate = pick("signal_engine_trace_sample_rate", g.ai_signal_engine_trace_sample_rate)
    timeout = pick("signal_engine_llm_timeout_seconds", g.ai_signal_engine_llm_timeout_seconds)

    sample_rate = _clamp01(_as_float(sample_rate, 1.0))
    timeout = _as_float(timeout, 8.0)
    if timeout <= 0:
        timeout = 8.0
    timeout = max(1.0, min(60.0, timeout))

    return SignalRuntimeConfig(
        enabled=bool(enabled),
        shadow_mode=bool(shadow),
        allow_legacy_fallback=bool(allow_legacy),
        min_confidence=_clamp01(_as_float(min_conf, 0.55)),
        min_actionability=_clamp01(_as_float(min_act, 0.55)),
        min_urgency=_clamp01(_as_float(min_urg, 0.45)),
        trace_enabled=bool(trace_enabled),
        trace_include_text=bool(trace_include_text),
        trace_sample_rate=sample_rate,
        llm_timeout_seconds=timeout,
        overrides_applied=applied,
    )
