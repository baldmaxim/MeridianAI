"""Этап 5: speaker_identity_hints в meeting AI settings (schema/validate/baseline)."""

from app.schemas.ai_settings import AISettingsResolved, MeetingAISettingsPatch
from app.services.ai_settings import config_baseline, validate_patch


def test_patch_schema_accepts_speaker_identity_hints():
    p = MeetingAISettingsPatch(speaker_identity_hints={"speaker_labels": {"SM_0": {"side": "our_side"}}})
    dumped = p.model_dump(exclude_unset=True)
    assert "speaker_identity_hints" in dumped
    assert dumped["speaker_identity_hints"]["speaker_labels"]["SM_0"]["side"] == "our_side"


def test_resolved_schema_accepts_speaker_identity_hints():
    r = AISettingsResolved(speaker_identity_hints={"stable_ids": {"speaker_x": {"side": "counterparty"}}})
    assert r.speaker_identity_hints["stable_ids"]["speaker_x"]["side"] == "counterparty"
    assert AISettingsResolved().speaker_identity_hints is None


def test_patch_schema_allows_explicit_null():
    p = MeetingAISettingsPatch(speaker_identity_hints=None)
    assert "speaker_identity_hints" in p.model_dump(exclude_unset=True)


def test_validate_patch_stores_normalized_hints():
    out = validate_patch({"speaker_identity_hints": {
        "speaker_labels": {"SM_0": {"side": "our_side", "confidence": 5.0}}}})
    e = out["speaker_identity_hints"]["speaker_labels"]["SM_0"]
    assert e["confidence"] == 0.98  # clamped
    assert e["source"] == "manual_correction"


def test_validate_patch_keeps_none_for_clearing():
    out = validate_patch({"speaker_identity_hints": None})
    assert "speaker_identity_hints" in out
    assert out["speaker_identity_hints"] is None


def test_validate_patch_absent_hints_not_added():
    out = validate_patch({"mode": "fast"})
    assert "speaker_identity_hints" not in out


def test_config_baseline_has_no_speaker_identity_hints():
    base = config_baseline()
    assert "speaker_identity_hints" not in base or base.get("speaker_identity_hints") is None


# --- Этап 21: контракт UI подтверждения ролей (форма патча из features/speakerIdentity) ---

# Точная форма, которую отдаёт frontend buildSpeakerIdentityHintsPatch (без PII).
_FRONTEND_PATCH = {
    "speaker_labels": {
        "SM_0": {"side": "our_side", "functional_role": "decision_maker",
                 "confidence": 0.95, "source": "manual_correction"}},
    "audio_sources": {
        "channel_0": {"side": "counterparty", "functional_role": "unknown",
                      "confidence": 0.75, "source": "audio_channel"}},
    "channel_labels": {
        "channel_1": {"side": "third_party", "functional_role": "observer",
                      "confidence": 0.75, "source": "audio_channel"}},
}


def test_validate_patch_accepts_frontend_shaped_patch():
    import json
    out = validate_patch({"speaker_identity_hints": _FRONTEND_PATCH})
    h = out["speaker_identity_hints"]
    assert set(h.keys()) == {"speaker_labels", "audio_sources", "channel_labels"}
    sm = h["speaker_labels"]["SM_0"]
    assert sm["side"] == "our_side" and sm["functional_role"] == "decision_maker"
    assert sm["source"] == "manual_correction" and sm["confidence"] == 0.95
    ch0 = h["audio_sources"]["channel_0"]
    assert ch0["side"] == "counterparty" and ch0["source"] == "audio_channel" and ch0["confidence"] == 0.75
    ch1 = h["channel_labels"]["channel_1"]
    assert ch1["side"] == "third_party" and ch1["functional_role"] == "observer"
    # Нет PII ни в одном значении сериализованного результата.
    blob = json.dumps(out, ensure_ascii=False)
    for banned in ("display_name", "organization", "raw_speaker_label"):
        assert banned not in blob


def test_validate_patch_drops_pii_from_hint_entry():
    out = validate_patch({"speaker_identity_hints": {"speaker_labels": {"SM_0": {
        "side": "our_side", "display_name": "Иван Иванов", "organization": "ООО Ромашка"}}}})
    entry = out["speaker_identity_hints"]["speaker_labels"]["SM_0"]
    assert "display_name" not in entry and "organization" not in entry
    assert set(entry.keys()) == {"side", "functional_role", "confidence", "source", "evidence"}
    assert entry["side"] == "our_side"


def test_validate_patch_audio_source_source_and_confidence():
    out = validate_patch({"speaker_identity_hints": {"audio_sources": {
        "channel_0": {"side": "counterparty", "confidence": 5.0}}}})
    e = out["speaker_identity_hints"]["audio_sources"]["channel_0"]
    assert e["source"] == "audio_channel"
    assert e["confidence"] == 0.85  # clamped к max аудио-группы


def test_validate_patch_unknown_side_zeroes_confidence():
    out = validate_patch({"speaker_identity_hints": {"speaker_labels": {
        "SM_9": {"side": "unknown", "confidence": 0.9}}}})
    e = out["speaker_identity_hints"]["speaker_labels"]["SM_9"]
    assert e["side"] == "unknown" and e["confidence"] == 0.0


def test_validate_patch_empty_groups_collapse_to_none():
    # Все строки unknown/пустые → нормализатор отдаёт None (эффективно очистка).
    out = validate_patch({"speaker_identity_hints": {"speaker_labels": {}}})
    assert out["speaker_identity_hints"] is None
