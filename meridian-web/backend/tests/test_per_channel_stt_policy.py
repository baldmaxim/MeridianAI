"""Per-channel STT canary policy resolver (Этап 17)."""

from types import SimpleNamespace

from app.config import get_settings
from app.core.context.per_channel_stt_policy import resolve_per_channel_stt_runtime_config


def _global(**ovr):
    base = dict(
        ai_audio_per_channel_stt_enabled=False,
        ai_audio_per_channel_stt_shadow_mode=True,
        ai_audio_per_channel_stt_session_overrides_enabled=True,
        ai_audio_per_channel_stt_trace_enabled=True,
        ai_audio_per_channel_stt_trace_sample_rate=1.0,
        ai_audio_per_channel_stt_max_channels=2,
        ai_audio_per_channel_stt_min_rms=0.012,
        ai_audio_per_channel_stt_min_dominance=0.58,
        ai_audio_per_channel_stt_min_segment_ms=700,
        ai_audio_per_channel_stt_end_silence_ms=700,
        ai_audio_per_channel_stt_max_segment_ms=8000,
        ai_audio_per_channel_stt_min_text_chars=4,
        ai_audio_per_channel_stt_max_segments_per_minute=12,
        ai_audio_per_channel_stt_max_concurrent_transcribes=2,
    )
    base.update(ovr)
    return SimpleNamespace(**base)


def test_global_defaults_disabled_shadow():
    c = resolve_per_channel_stt_runtime_config(_global())
    assert c.enabled is False
    assert c.shadow_mode is True
    assert all(v is False for v in c.overrides_applied.values())


def test_real_settings_defaults_safe():
    c = resolve_per_channel_stt_runtime_config(get_settings())
    assert c.enabled is False and c.shadow_mode is True  # прод-дефолт безопасный


def test_session_overrides_applied():
    c = resolve_per_channel_stt_runtime_config(_global(), {
        "audio_per_channel_stt_enabled": True, "audio_per_channel_stt_shadow_mode": False,
        "audio_per_channel_stt_min_dominance": 0.7})
    assert c.enabled is True
    assert c.shadow_mode is False
    assert c.min_dominance == 0.7
    assert c.overrides_applied["audio_per_channel_stt_enabled"] is True
    assert c.overrides_applied["audio_per_channel_stt_shadow_mode"] is True


def test_overrides_ignored_when_disabled():
    g = _global(ai_audio_per_channel_stt_session_overrides_enabled=False)
    c = resolve_per_channel_stt_runtime_config(g, {"audio_per_channel_stt_enabled": True})
    assert c.enabled is False  # override проигнорирован (kill-switch)
    assert c.session_overrides_enabled is False
    assert all(v is False for v in c.overrides_applied.values())


def test_none_means_global():
    c = resolve_per_channel_stt_runtime_config(_global(), {"audio_per_channel_stt_enabled": None})
    assert c.enabled is False
    assert c.overrides_applied["audio_per_channel_stt_enabled"] is False


def test_object_session_ai_supported():
    sess = SimpleNamespace(audio_per_channel_stt_enabled=True)
    c = resolve_per_channel_stt_runtime_config(_global(), sess)
    assert c.enabled is True


def test_clamps():
    c = resolve_per_channel_stt_runtime_config(_global(), {
        "audio_per_channel_stt_trace_sample_rate": 5.0,
        "audio_per_channel_stt_max_channels": 99,
        "audio_per_channel_stt_min_rms": -1,
        "audio_per_channel_stt_min_dominance": 2.0,
        "audio_per_channel_stt_min_segment_ms": 5,
        "audio_per_channel_stt_end_silence_ms": 99999,
        "audio_per_channel_stt_max_segment_ms": 1,
        "audio_per_channel_stt_min_text_chars": 999,
        "audio_per_channel_stt_max_segments_per_minute": 0,
        "audio_per_channel_stt_max_concurrent_transcribes": 50,
    })
    assert c.trace_sample_rate == 1.0
    assert c.max_channels == 8
    assert c.min_rms == 0.0
    assert c.min_dominance == 1.0
    assert c.min_segment_ms == 100
    assert c.end_silence_ms == 5000
    assert c.max_segment_ms == 500
    assert c.min_text_chars == 80
    assert c.max_segments_per_minute == 1
    assert c.max_concurrent_transcribes == 8


# --- Stage 18: provider config ---

def test_provider_defaults():
    c = resolve_per_channel_stt_runtime_config(_global())
    assert c.provider == "noop"
    assert c.timeout_seconds == 20.0
    assert c.language_code == "ru"
    assert c.cache_enabled is True
    assert c.max_provider_calls_per_meeting == 60


def test_provider_overrides_and_normalization():
    c = resolve_per_channel_stt_runtime_config(_global(), {
        "audio_per_channel_stt_provider": "  ElevenLabs_Batch  ",
        "audio_per_channel_stt_language_code": "en",
        "audio_per_channel_stt_model_id": "scribe_v2"})
    assert c.provider == "elevenlabs_batch"   # normalized lower + stripped
    assert c.language_code == "en"
    assert c.model_id == "scribe_v2"


def test_provider_unknown_kept_lower():
    c = resolve_per_channel_stt_runtime_config(_global(), {"audio_per_channel_stt_provider": "WeirdX"})
    assert c.provider == "weirdx"  # допускается, downstream → no-op/static error


def test_provider_clamps():
    c = resolve_per_channel_stt_runtime_config(_global(), {
        "audio_per_channel_stt_timeout_seconds": 999.0,
        "audio_per_channel_stt_max_audio_seconds": 999.0,
        "audio_per_channel_stt_max_wav_bytes": 10,
        "audio_per_channel_stt_cache_max_entries": 999999,
        "audio_per_channel_stt_max_provider_calls_per_meeting": 99999,
        "audio_per_channel_stt_max_provider_audio_seconds_per_meeting": 99999.0,
        "audio_per_channel_stt_model_id": "x" * 500})
    assert c.timeout_seconds == 120.0
    assert c.max_audio_seconds == 60.0
    assert c.max_wav_bytes == 65536
    assert c.cache_max_entries == 5000
    assert c.max_provider_calls_per_meeting == 1000
    assert c.max_provider_audio_seconds_per_meeting == 7200.0
    assert len(c.model_id) == 80


def test_provider_long_secret_like_model_truncated():
    # model_id не должен быть длинным «секретом» — обрезается
    c = resolve_per_channel_stt_runtime_config(_global(), {"audio_per_channel_stt_model_id": "sk-" + "a" * 200})
    assert len(c.model_id) <= 80
