"""Hidden per-meeting canary override audio_per_channel_stt_* (Этап 17)."""

from app.schemas.ai_settings import AISettingsProfileCreate, MeetingAISettingsPatch
from app.services.ai_settings import config_baseline, validate_patch


def test_patch_schema_accepts_hidden_fields():
    p = MeetingAISettingsPatch(
        audio_per_channel_stt_enabled=True, audio_per_channel_stt_shadow_mode=False,
        audio_per_channel_stt_min_dominance=0.7, audio_per_channel_stt_max_channels=4)
    d = p.model_dump(exclude_unset=True)
    assert d["audio_per_channel_stt_enabled"] is True
    assert d["audio_per_channel_stt_min_dominance"] == 0.7


def test_profile_schema_has_no_hidden_fields():
    assert "audio_per_channel_stt_enabled" not in AISettingsProfileCreate.model_fields


def test_validate_patch_accepts_bool_float_int():
    out = validate_patch({
        "audio_per_channel_stt_enabled": True,
        "audio_per_channel_stt_shadow_mode": False,
        "audio_per_channel_stt_trace_sample_rate": 0.5,
        "audio_per_channel_stt_min_rms": 0.02,
        "audio_per_channel_stt_min_dominance": 0.65,
        "audio_per_channel_stt_max_channels": 4,
        "audio_per_channel_stt_min_segment_ms": 800,
        "audio_per_channel_stt_max_concurrent_transcribes": 3,
    })
    assert out["audio_per_channel_stt_enabled"] is True
    assert out["audio_per_channel_stt_shadow_mode"] is False
    assert out["audio_per_channel_stt_trace_sample_rate"] == 0.5
    assert out["audio_per_channel_stt_max_channels"] == 4


def test_validate_patch_clamps():
    out = validate_patch({
        "audio_per_channel_stt_min_dominance": 5.0,       # → 1.0
        "audio_per_channel_stt_max_channels": 99,          # → 8
        "audio_per_channel_stt_min_segment_ms": 5,         # → 100
        "audio_per_channel_stt_max_segments_per_minute": 999,  # → 120
    })
    assert out["audio_per_channel_stt_min_dominance"] == 1.0
    assert out["audio_per_channel_stt_max_channels"] == 8
    assert out["audio_per_channel_stt_min_segment_ms"] == 100
    assert out["audio_per_channel_stt_max_segments_per_minute"] == 120


def test_validate_patch_preserves_none_for_rollback():
    out = validate_patch({
        "audio_per_channel_stt_enabled": None,
        "audio_per_channel_stt_min_dominance": None,
        "audio_per_channel_stt_max_channels": None})
    assert out["audio_per_channel_stt_enabled"] is None
    assert out["audio_per_channel_stt_min_dominance"] is None
    assert out["audio_per_channel_stt_max_channels"] is None


def test_config_baseline_does_not_freeze_per_channel_stt():
    base = config_baseline()
    assert not any(k.startswith("audio_per_channel_stt_") for k in base)


# --- Stage 18: provider hidden fields ---

def test_patch_schema_accepts_provider_fields():
    p = MeetingAISettingsPatch(
        audio_per_channel_stt_provider="elevenlabs_batch",
        audio_per_channel_stt_timeout_seconds=15.0,
        audio_per_channel_stt_language_code="ru",
        audio_per_channel_stt_max_provider_calls_per_meeting=30)
    d = p.model_dump(exclude_unset=True)
    assert d["audio_per_channel_stt_provider"] == "elevenlabs_batch"
    assert d["audio_per_channel_stt_timeout_seconds"] == 15.0


def test_validate_patch_provider_fields():
    out = validate_patch({
        "audio_per_channel_stt_provider": "  elevenlabs_batch ",
        "audio_per_channel_stt_timeout_seconds": 999.0,        # clamp → 120
        "audio_per_channel_stt_language_code": "en",
        "audio_per_channel_stt_model_id": "x" * 200,            # truncate → 80
        "audio_per_channel_stt_cache_enabled": False,
        "audio_per_channel_stt_max_wav_bytes": 10,              # clamp → 65536
        "audio_per_channel_stt_max_provider_calls_per_meeting": 99999,  # clamp → 1000
    })
    assert out["audio_per_channel_stt_provider"] == "elevenlabs_batch"
    assert out["audio_per_channel_stt_timeout_seconds"] == 120.0
    assert out["audio_per_channel_stt_cache_enabled"] is False
    assert out["audio_per_channel_stt_max_wav_bytes"] == 65536
    assert out["audio_per_channel_stt_max_provider_calls_per_meeting"] == 1000
    assert len(out["audio_per_channel_stt_model_id"]) == 80


def test_validate_patch_provider_none_rollback():
    out = validate_patch({
        "audio_per_channel_stt_provider": None,
        "audio_per_channel_stt_timeout_seconds": None,
        "audio_per_channel_stt_max_provider_calls_per_meeting": None})
    assert out["audio_per_channel_stt_provider"] is None
    assert out["audio_per_channel_stt_timeout_seconds"] is None
    assert out["audio_per_channel_stt_max_provider_calls_per_meeting"] is None


def test_profile_schema_has_no_provider_fields():
    assert "audio_per_channel_stt_provider" not in AISettingsProfileCreate.model_fields
