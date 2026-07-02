"""Speaker Identity Hints v1 (Этап 5): нормализация hidden hints + source helper."""

import pytest

from app.core.context.speaker_identity import (
    normalize_identity_hints,
    normalize_speaker_identity_source,
)
from app.services.ai_settings import validate_speaker_identity_hints


def test_accepts_speaker_labels():
    out = normalize_identity_hints({
        "speaker_labels": {"SM_0": {"side": "our_side", "functional_role": "project_manager",
                                    "confidence": 0.95, "source": "manual_correction"}}
    })
    e = out["speaker_labels"]["SM_0"]
    assert e["side"] == "our_side"
    assert e["functional_role"] == "project_manager"
    assert e["confidence"] == 0.95
    assert e["source"] == "manual_correction"
    assert e["evidence"] == []


def test_accepts_stable_ids():
    out = normalize_identity_hints({"stable_ids": {"speaker_a1b2c3d4": {"side": "our_side", "confidence": 0.9}}})
    assert out["stable_ids"]["speaker_a1b2c3d4"]["side"] == "our_side"
    assert out["stable_ids"]["speaker_a1b2c3d4"]["source"] == "manual_correction"  # default


def test_accepts_audio_sources_and_channel_labels():
    out = normalize_identity_hints({
        "audio_sources": {"primary": {"side": "our_side"}},
        "channel_labels": {"left": {"side": "our_side"}},
    })
    assert out["audio_sources"]["primary"]["source"] == "audio_channel"  # default
    assert out["audio_sources"]["primary"]["confidence"] == 0.75  # default
    assert out["channel_labels"]["left"]["source"] == "audio_channel"


def test_confidence_clamp_speaker_labels_max_098():
    out = normalize_identity_hints({"speaker_labels": {"SM_0": {"side": "our_side", "confidence": 5.0}}})
    assert out["speaker_labels"]["SM_0"]["confidence"] == 0.98


def test_confidence_clamp_audio_channel_max_085():
    out = normalize_identity_hints({"audio_sources": {"primary": {"side": "our_side", "confidence": 5.0}}})
    assert out["audio_sources"]["primary"]["confidence"] == 0.85


def test_unknown_side_confidence_zeroed():
    out = normalize_identity_hints({"speaker_labels": {"SM_0": {"confidence": 0.95}}})  # no side
    e = out["speaker_labels"]["SM_0"]
    assert e["side"] == "unknown"
    assert e["confidence"] == 0.0  # unknown не становится уверенным


def test_none_clears_override():
    assert normalize_identity_hints(None) is None
    assert validate_speaker_identity_hints(None) is None


def test_invalid_type_rejected():
    with pytest.raises(ValueError):
        normalize_identity_hints("not-a-dict")
    with pytest.raises(ValueError):
        normalize_identity_hints([1, 2, 3])


def test_display_name_and_org_not_stored():
    out = normalize_identity_hints({
        "speaker_labels": {"SM_0": {"side": "our_side", "display_name": "Иван Петров",
                                    "organization": "ООО Ромашка", "raw_speaker_label": "x"}}
    })
    e = out["speaker_labels"]["SM_0"]
    assert "display_name" not in e
    assert "organization" not in e
    assert "raw_speaker_label" not in e
    assert set(e.keys()) == {"side", "functional_role", "confidence", "source", "evidence"}


def test_unknown_top_level_group_ignored():
    # неизвестные группы игнорируются; если валидных нет — None
    assert normalize_identity_hints({"bogus_group": {"x": {"side": "our_side"}}}) is None
    out = normalize_identity_hints({
        "bogus_group": {"x": {}}, "speaker_labels": {"SM_0": {"side": "our_side"}},
    })
    assert set(out.keys()) == {"speaker_labels"}


def test_evidence_trimmed():
    out = normalize_identity_hints({
        "speaker_labels": {"SM_0": {"side": "our_side", "evidence": ["x" * 500, "", 123, "ok"]}}
    })
    ev = out["speaker_labels"]["SM_0"]["evidence"]
    assert len(ev[0]) <= 120
    assert "ok" in ev
    assert "" not in ev


def test_normalize_speaker_identity_source():
    assert normalize_speaker_identity_source("manual_correction") == "manual_correction"
    assert normalize_speaker_identity_source("audio_channel") == "audio_channel"
    assert normalize_speaker_identity_source("bogus") == "unknown"
    assert normalize_speaker_identity_source(None) == "unknown"


def test_validate_speaker_identity_hints_delegates():
    out = validate_speaker_identity_hints({"speaker_labels": {"SM_0": {"side": "counterparty"}}})
    assert out["speaker_labels"]["SM_0"]["side"] == "counterparty"
