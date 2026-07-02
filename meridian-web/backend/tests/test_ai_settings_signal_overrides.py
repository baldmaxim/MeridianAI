"""Этап 3: hidden Signal Engine overrides в meeting AI settings + resolver gating."""

from types import SimpleNamespace

from app.schemas.ai_settings import AISettingsResolved, MeetingAISettingsPatch
from app.services.ai_settings import config_baseline, validate_patch
from app.core.context.signal_policy import resolve_signal_runtime_config


# --- validate_patch: hidden signal keys ---

def test_validate_patch_accepts_shadow_mode_false():
    out = validate_patch({"signal_engine_shadow_mode": False})
    assert out["signal_engine_shadow_mode"] is False


def test_validate_patch_clamps_float_thresholds():
    out = validate_patch({
        "signal_engine_min_confidence": 1.5,
        "signal_engine_min_actionability": -0.2,
        "signal_engine_trace_sample_rate": 0.3,
    })
    assert out["signal_engine_min_confidence"] == 1.0
    assert out["signal_engine_min_actionability"] == 0.0
    assert out["signal_engine_trace_sample_rate"] == 0.3


def test_validate_patch_clamps_timeout():
    assert validate_patch({"signal_engine_llm_timeout_seconds": 0.5})["signal_engine_llm_timeout_seconds"] == 1.0
    assert validate_patch({"signal_engine_llm_timeout_seconds": 999})["signal_engine_llm_timeout_seconds"] == 60.0
    assert validate_patch({"signal_engine_llm_timeout_seconds": 12})["signal_engine_llm_timeout_seconds"] == 12.0


def test_validate_patch_keeps_none_for_clearing():
    out = validate_patch({
        "signal_engine_shadow_mode": None,
        "signal_engine_min_confidence": None,
        "signal_engine_llm_timeout_seconds": None,
    })
    assert out["signal_engine_shadow_mode"] is None
    assert out["signal_engine_min_confidence"] is None
    assert out["signal_engine_llm_timeout_seconds"] is None


def test_validate_patch_ignores_absent_signal_keys():
    out = validate_patch({"mode": "fast"})
    assert not any(k.startswith("signal_engine_") for k in out)


# --- config_baseline не замораживает global signal values ---

def test_config_baseline_has_no_frozen_signal_values():
    base = config_baseline()
    for k, v in base.items():
        if k.startswith("signal_engine_"):
            assert v is None  # допускается только None, не true/false/float


def test_config_baseline_signal_keys_absent_or_none():
    base = config_baseline()
    signal_keys = [k for k in base if k.startswith("signal_engine_")]
    # либо ключей нет вовсе, либо они None
    assert signal_keys == [] or all(base[k] is None for k in signal_keys)


# --- схемы принимают hidden поля ---

def test_resolved_schema_accepts_signal_fields():
    r = AISettingsResolved(signal_engine_shadow_mode=False, signal_engine_min_confidence=0.7)
    assert r.signal_engine_shadow_mode is False
    assert r.signal_engine_min_confidence == 0.7
    # по умолчанию None (скрытые, не выводятся как профильные)
    assert AISettingsResolved().signal_engine_enabled is None


def test_patch_schema_accepts_signal_fields():
    p = MeetingAISettingsPatch(signal_engine_enabled=True, signal_engine_trace_sample_rate=0.5)
    dumped = p.model_dump(exclude_unset=True)
    assert dumped["signal_engine_enabled"] is True
    assert dumped["signal_engine_trace_sample_rate"] == 0.5
    # не переданные ключи не попадают в patch
    assert "signal_engine_shadow_mode" not in dumped


def test_patch_schema_allows_explicit_null():
    p = MeetingAISettingsPatch(signal_engine_shadow_mode=None)
    dumped = p.model_dump(exclude_unset=True)
    assert "signal_engine_shadow_mode" in dumped
    assert dumped["signal_engine_shadow_mode"] is None


# --- resolver gating: SESSION_OVERRIDES_ENABLED / trace text ---

class _G:
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


def _g(**kw):
    g = _G()
    for k, v in kw.items():
        setattr(g, k, v)
    return g


def test_resolver_applies_overrides_when_enabled():
    cfg = resolve_signal_runtime_config(_g(), {"signal_engine_shadow_mode": False})
    assert cfg.shadow_mode is False
    assert cfg.overrides_applied["signal_engine_shadow_mode"] is True


def test_resolver_ignores_overrides_when_disabled():
    cfg = resolve_signal_runtime_config(
        _g(ai_signal_engine_session_overrides_enabled=False),
        {"signal_engine_shadow_mode": False, "signal_engine_enabled": False},
    )
    assert cfg.shadow_mode is True  # global preserved
    assert cfg.enabled is True
    assert cfg.overrides_applied["signal_engine_shadow_mode"] is False


def test_resolver_blocks_trace_text_override_by_default():
    cfg = resolve_signal_runtime_config(_g(), {"signal_engine_trace_include_text": True})
    assert cfg.trace_include_text is False
    assert cfg.overrides_applied["signal_engine_trace_include_text"] is False


def test_resolver_allows_trace_text_override_when_globally_allowed():
    cfg = resolve_signal_runtime_config(
        _g(ai_signal_engine_session_trace_text_override_allowed=True),
        {"signal_engine_trace_include_text": True},
    )
    assert cfg.trace_include_text is True
    assert cfg.overrides_applied["signal_engine_trace_include_text"] is True


def test_resolver_object_session_ai():
    session = SimpleNamespace(signal_engine_min_confidence=0.8)
    cfg = resolve_signal_runtime_config(_g(), session)
    assert cfg.min_confidence == 0.8
