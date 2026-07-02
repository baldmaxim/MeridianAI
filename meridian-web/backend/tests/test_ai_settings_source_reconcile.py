"""Этап 11: source_reconcile_* hidden fields в meeting AI settings."""

from app.schemas.ai_settings import AISettingsResolved, MeetingAISettingsPatch
from app.services.ai_settings import config_baseline, validate_patch


def test_patch_schema_accepts_source_reconcile_fields():
    p = MeetingAISettingsPatch(source_reconcile_shadow_mode=False, source_reconcile_min_match_score=0.7)
    d = p.model_dump(exclude_unset=True)
    assert d["source_reconcile_shadow_mode"] is False
    assert d["source_reconcile_min_match_score"] == 0.7


def test_resolved_schema_accepts_source_reconcile_fields():
    r = AISettingsResolved(source_reconcile_enabled=True, source_reconcile_max_candidates=100)
    assert r.source_reconcile_enabled is True
    assert r.source_reconcile_max_candidates == 100
    assert AISettingsResolved().source_reconcile_shadow_mode is None


def test_validate_patch_accepts_and_clamps():
    out = validate_patch({
        "source_reconcile_shadow_mode": False,
        "source_reconcile_min_text_similarity": 5.0,        # clamp → 1.0
        "source_reconcile_ambiguity_margin": 9.0,           # clamp → 0.5
        "source_reconcile_max_candidates": 999999,          # clamp → 5000
        "source_reconcile_max_age_ms": 5,                   # clamp → 1000
    })
    assert out["source_reconcile_shadow_mode"] is False
    assert out["source_reconcile_min_text_similarity"] == 1.0
    assert out["source_reconcile_ambiguity_margin"] == 0.5
    assert out["source_reconcile_max_candidates"] == 5000
    assert out["source_reconcile_max_age_ms"] == 1000


def test_validate_patch_keeps_none_for_clearing():
    out = validate_patch({"source_reconcile_shadow_mode": None,
                          "source_reconcile_min_match_score": None,
                          "source_reconcile_max_candidates": None})
    assert out["source_reconcile_shadow_mode"] is None
    assert out["source_reconcile_min_match_score"] is None
    assert out["source_reconcile_max_candidates"] is None


def test_validate_patch_absent_keys_not_added():
    out = validate_patch({"mode": "fast"})
    assert not any(k.startswith("source_reconcile_") for k in out)


def test_config_baseline_no_source_reconcile_values():
    base = config_baseline()
    for k, v in base.items():
        if k.startswith("source_reconcile_"):
            assert v is None
