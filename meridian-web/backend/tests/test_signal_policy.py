"""Signal Engine policy (Этап 2): gating-решение и resolve runtime-конфига."""

from types import SimpleNamespace

from app.core.context.signal_engine import NegotiationSignal, SignalEngineResult
from app.core.context.signal_policy import (
    SignalRuntimeConfig,
    evaluate_signal_decision,
    resolve_signal_runtime_config,
)


def _cfg(**kw) -> SignalRuntimeConfig:
    base = dict(
        enabled=True, shadow_mode=False, allow_legacy_fallback=True,
        min_confidence=0.55, min_actionability=0.55, min_urgency=0.45,
    )
    base.update(kw)
    return SignalRuntimeConfig(**base)


def _strong(**kw) -> NegotiationSignal:
    d = dict(
        should_prompt=True, situation_type="price_pressure",
        confidence=0.8, actionability=0.7, urgency=0.6,
        novelty_key="price_pressure:counterparty:x",
    )
    d.update(kw)
    return NegotiationSignal(**d)


def _res(signal, error_kind="none", used_fallback=False) -> SignalEngineResult:
    return SignalEngineResult(signal=signal, error_kind=error_kind, used_fallback=used_fallback)


# --- evaluate_signal_decision ---

def test_strong_signal_live_is_allowed():
    sig = _strong()
    d = evaluate_signal_decision(sig, _res(sig), _cfg(shadow_mode=False))
    assert d.actual_should_prompt is True
    assert d.would_prompt_without_shadow is True
    assert d.reason == "allowed"
    assert d.cooldown_key == "signal:price_pressure:counterparty:x"
    assert 0.0 <= d.score <= 1.0


def test_strong_signal_shadow_does_not_prompt():
    sig = _strong()
    d = evaluate_signal_decision(sig, _res(sig), _cfg(shadow_mode=True))
    assert d.actual_should_prompt is False
    assert d.would_prompt_without_shadow is True
    assert d.reason == "shadow_mode"
    assert d.cooldown_key == "signal:price_pressure:counterparty:x"


def test_disabled_reason():
    sig = _strong()
    d = evaluate_signal_decision(sig, _res(sig), _cfg(enabled=False))
    assert d.actual_should_prompt is False
    assert d.reason == "disabled"
    assert d.legacy_fallback_allowed is False


def test_should_prompt_false_no_legacy():
    sig = NegotiationSignal(should_prompt=False)
    d = evaluate_signal_decision(sig, _res(sig), _cfg(shadow_mode=False))
    assert d.actual_should_prompt is False
    assert d.legacy_fallback_allowed is False
    assert d.reason == "should_prompt_false"


def test_low_confidence_blocks():
    sig = _strong(confidence=0.4)
    d = evaluate_signal_decision(sig, _res(sig), _cfg(shadow_mode=False))
    assert d.actual_should_prompt is False
    assert d.reason == "low_confidence"
    assert d.legacy_fallback_allowed is False


def test_low_actionability_blocks():
    sig = _strong(actionability=0.4)
    d = evaluate_signal_decision(sig, _res(sig), _cfg(shadow_mode=False))
    assert d.reason == "low_actionability"


def test_low_urgency_blocks():
    sig = _strong(urgency=0.3)
    d = evaluate_signal_decision(sig, _res(sig), _cfg(shadow_mode=False))
    assert d.reason == "low_urgency"


def test_llm_unavailable_with_legacy_allowed():
    none_sig = NegotiationSignal()
    res = _res(none_sig, error_kind="llm_unavailable", used_fallback=True)
    d = evaluate_signal_decision(none_sig, res, _cfg(allow_legacy_fallback=True))
    assert d.legacy_fallback_allowed is True
    assert d.reason == "technical_error_legacy_allowed"
    assert d.actual_should_prompt is False


def test_timeout_without_legacy():
    none_sig = NegotiationSignal()
    res = _res(none_sig, error_kind="timeout", used_fallback=True)
    d = evaluate_signal_decision(none_sig, res, _cfg(allow_legacy_fallback=False))
    assert d.legacy_fallback_allowed is False
    assert d.reason == "technical_error_no_legacy"


def test_invalid_json_no_legacy():
    none_sig = NegotiationSignal()
    res = _res(none_sig, error_kind="invalid_json", used_fallback=True)
    d = evaluate_signal_decision(none_sig, res, _cfg(allow_legacy_fallback=True))
    assert d.legacy_fallback_allowed is False
    assert d.reason == "model_output_invalid"


def test_validation_error_no_legacy():
    none_sig = NegotiationSignal()
    res = _res(none_sig, error_kind="validation_error", used_fallback=True)
    d = evaluate_signal_decision(none_sig, res, _cfg(allow_legacy_fallback=True))
    assert d.legacy_fallback_allowed is False
    assert d.reason == "model_output_invalid"


# --- resolve_signal_runtime_config ---

class _Globals:
    ai_signal_engine_enabled = True
    ai_signal_engine_shadow_mode = True
    ai_signal_engine_allow_legacy_fallback = True
    ai_signal_engine_min_confidence = 0.55
    ai_signal_engine_min_actionability = 0.55
    ai_signal_engine_min_urgency = 0.45
    ai_signal_engine_trace_enabled = True
    ai_signal_engine_trace_include_text = False
    ai_signal_engine_trace_sample_rate = 1.0
    ai_signal_engine_llm_timeout_seconds = 8.0
    ai_signal_engine_session_overrides_enabled = True
    ai_signal_engine_session_trace_text_override_allowed = False


def test_resolver_global_defaults():
    cfg = resolve_signal_runtime_config(_Globals(), session_ai=None)
    assert cfg.enabled is True
    assert cfg.shadow_mode is True
    assert cfg.allow_legacy_fallback is True
    assert cfg.min_confidence == 0.55
    assert cfg.trace_include_text is False
    assert cfg.trace_sample_rate == 1.0
    assert cfg.llm_timeout_seconds == 8.0


def test_resolver_dict_overrides():
    session_ai = {
        "signal_engine_shadow_mode": False,
        "signal_engine_min_confidence": 0.9,
        "signal_engine_trace_include_text": True,
    }
    cfg = resolve_signal_runtime_config(_Globals(), session_ai)
    assert cfg.shadow_mode is False  # override
    assert cfg.min_confidence == 0.9  # override
    # trace_include_text override игнорируется без глобального разрешения (Этап 3)
    assert cfg.trace_include_text is False
    assert cfg.enabled is True  # global default preserved
    assert cfg.overrides_applied["signal_engine_shadow_mode"] is True
    assert cfg.overrides_applied["signal_engine_trace_include_text"] is False


def test_resolver_object_attribute_overrides():
    session_ai = SimpleNamespace(signal_engine_enabled=False, signal_engine_shadow_mode=False)
    cfg = resolve_signal_runtime_config(_Globals(), session_ai)
    assert cfg.enabled is False
    assert cfg.shadow_mode is False
    assert cfg.min_urgency == 0.45  # global default preserved


def test_resolver_sample_rate_clamped():
    high = resolve_signal_runtime_config(_Globals(), {"signal_engine_trace_sample_rate": 5.0})
    assert high.trace_sample_rate == 1.0
    low = resolve_signal_runtime_config(_Globals(), {"signal_engine_trace_sample_rate": -1.0})
    assert low.trace_sample_rate == 0.0


def test_resolver_timeout_not_nonpositive():
    zero = resolve_signal_runtime_config(_Globals(), {"signal_engine_llm_timeout_seconds": 0})
    assert zero.llm_timeout_seconds == 8.0
    neg = resolve_signal_runtime_config(_Globals(), {"signal_engine_llm_timeout_seconds": -3})
    assert neg.llm_timeout_seconds == 8.0
    ok = resolve_signal_runtime_config(_Globals(), {"signal_engine_llm_timeout_seconds": 2.5})
    assert ok.llm_timeout_seconds == 2.5


def test_resolver_none_override_falls_back_to_global():
    # явный None в session_ai не должен затирать глобальное значение
    cfg = resolve_signal_runtime_config(_Globals(), {"signal_engine_shadow_mode": None})
    assert cfg.shadow_mode is True
