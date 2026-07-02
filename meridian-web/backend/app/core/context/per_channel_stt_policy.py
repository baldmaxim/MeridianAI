"""Per-channel STT canary policy (Этап 17): runtime config resolver.

Собирает PerChannelSttRuntimeConfig из global config + опционального per-meeting canary override
(hidden audio_per_channel_stt_* ключи). Без побочных эффектов и LLM. По умолчанию enabled=false,
shadow=true — безопасно. channel_{index} — техническая зона записи, не сторона.
"""

from typing import Any

from pydantic import BaseModel

_MISSING = object()


class PerChannelSttRuntimeConfig(BaseModel):
    enabled: bool
    shadow_mode: bool
    session_overrides_enabled: bool
    trace_enabled: bool
    trace_sample_rate: float
    max_channels: int
    min_rms: float
    min_dominance: float
    min_segment_ms: int
    end_silence_ms: int
    max_segment_ms: int
    min_text_chars: int
    max_segments_per_minute: int
    max_concurrent_transcribes: int
    # Provider adapter (Этап 18)
    provider: str = "noop"
    timeout_seconds: float = 20.0
    language_code: str = "ru"
    model_id: str = ""
    cache_enabled: bool = True
    cache_max_entries: int = 512
    max_audio_seconds: float = 12.0
    max_wav_bytes: int = 1048576
    max_provider_calls_per_meeting: int = 60
    max_provider_audio_seconds_per_meeting: float = 300.0
    overrides_applied: dict = {}


_ALLOWED_PROVIDERS = {"noop", "elevenlabs_batch", "existing_batch"}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_token(v, default: str, max_len: int) -> str:
    """Безопасный короткий токен (provider/language/model): без секретов/переводов строк."""
    if v is None:
        return default
    s = " ".join(str(v).split()).strip()
    if not s:
        return default
    return s[:max_len]


def _normalize_provider(v) -> str:
    s = _safe_token(v, "noop", 40).lower()
    # unknown допускается, но downstream резолвится в no-op behavior
    return s


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _session_get(session_ai: Any, key: str):
    if session_ai is None:
        return _MISSING
    val = session_ai.get(key, _MISSING) if isinstance(session_ai, dict) else getattr(session_ai, key, _MISSING)
    return _MISSING if val is None else val


def resolve_per_channel_stt_runtime_config(global_settings, session_ai: Any = None) -> PerChannelSttRuntimeConfig:
    """Runtime config из global config + опц. per-meeting canary override.

    session_ai (dict/object) ключи audio_per_channel_stt_* перекрывают global ТОЛЬКО если
    session_overrides_enabled. None = «использовать global». Все пороги/лимиты clamp.
    """
    g = global_settings
    overrides_enabled = bool(getattr(g, "ai_audio_per_channel_stt_session_overrides_enabled", True))
    applied: dict = {}

    def pick(key: str, default):
        if not overrides_enabled:
            applied[key] = False
            return default
        val = _session_get(session_ai, key)
        if val is _MISSING:
            applied[key] = False
            return default
        applied[key] = True
        return val

    enabled = pick("audio_per_channel_stt_enabled", g.ai_audio_per_channel_stt_enabled)
    shadow = pick("audio_per_channel_stt_shadow_mode", g.ai_audio_per_channel_stt_shadow_mode)
    trace_enabled = pick("audio_per_channel_stt_trace_enabled", g.ai_audio_per_channel_stt_trace_enabled)
    sample_rate = pick("audio_per_channel_stt_trace_sample_rate", g.ai_audio_per_channel_stt_trace_sample_rate)
    max_channels = pick("audio_per_channel_stt_max_channels", g.ai_audio_per_channel_stt_max_channels)
    min_rms = pick("audio_per_channel_stt_min_rms", g.ai_audio_per_channel_stt_min_rms)
    min_dominance = pick("audio_per_channel_stt_min_dominance", g.ai_audio_per_channel_stt_min_dominance)
    min_segment_ms = pick("audio_per_channel_stt_min_segment_ms", g.ai_audio_per_channel_stt_min_segment_ms)
    end_silence_ms = pick("audio_per_channel_stt_end_silence_ms", g.ai_audio_per_channel_stt_end_silence_ms)
    max_segment_ms = pick("audio_per_channel_stt_max_segment_ms", g.ai_audio_per_channel_stt_max_segment_ms)
    min_text_chars = pick("audio_per_channel_stt_min_text_chars", g.ai_audio_per_channel_stt_min_text_chars)
    max_seg_per_min = pick("audio_per_channel_stt_max_segments_per_minute",
                           g.ai_audio_per_channel_stt_max_segments_per_minute)
    max_concurrent = pick("audio_per_channel_stt_max_concurrent_transcribes",
                          g.ai_audio_per_channel_stt_max_concurrent_transcribes)
    provider = pick("audio_per_channel_stt_provider", getattr(g, "ai_audio_per_channel_stt_provider", "noop"))
    timeout_s = pick("audio_per_channel_stt_timeout_seconds",
                     getattr(g, "ai_audio_per_channel_stt_timeout_seconds", 20.0))
    language_code = pick("audio_per_channel_stt_language_code",
                         getattr(g, "ai_audio_per_channel_stt_language_code", "ru"))
    model_id = pick("audio_per_channel_stt_model_id", getattr(g, "ai_audio_per_channel_stt_model_id", ""))
    cache_enabled = pick("audio_per_channel_stt_cache_enabled",
                         getattr(g, "ai_audio_per_channel_stt_cache_enabled", True))
    cache_max_entries = pick("audio_per_channel_stt_cache_max_entries",
                             getattr(g, "ai_audio_per_channel_stt_cache_max_entries", 512))
    max_audio_s = pick("audio_per_channel_stt_max_audio_seconds",
                       getattr(g, "ai_audio_per_channel_stt_max_audio_seconds", 12.0))
    max_wav_bytes = pick("audio_per_channel_stt_max_wav_bytes",
                         getattr(g, "ai_audio_per_channel_stt_max_wav_bytes", 1048576))
    max_calls = pick("audio_per_channel_stt_max_provider_calls_per_meeting",
                     getattr(g, "ai_audio_per_channel_stt_max_provider_calls_per_meeting", 60))
    max_audio_per_meeting = pick("audio_per_channel_stt_max_provider_audio_seconds_per_meeting",
                                 getattr(g, "ai_audio_per_channel_stt_max_provider_audio_seconds_per_meeting", 300.0))

    return PerChannelSttRuntimeConfig(
        enabled=bool(enabled),
        shadow_mode=bool(shadow),
        session_overrides_enabled=overrides_enabled,
        trace_enabled=bool(trace_enabled),
        trace_sample_rate=_clamp(_as_float(sample_rate, 1.0), 0.0, 1.0),
        max_channels=int(_clamp(_as_int(max_channels, 2), 1, 8)),
        min_rms=_clamp(_as_float(min_rms, 0.012), 0.0, 1.0),
        min_dominance=_clamp(_as_float(min_dominance, 0.58), 0.0, 1.0),
        min_segment_ms=int(_clamp(_as_int(min_segment_ms, 700), 100, 10000)),
        end_silence_ms=int(_clamp(_as_int(end_silence_ms, 700), 100, 5000)),
        max_segment_ms=int(_clamp(_as_int(max_segment_ms, 8000), 500, 30000)),
        min_text_chars=int(_clamp(_as_int(min_text_chars, 4), 0, 80)),
        max_segments_per_minute=int(_clamp(_as_int(max_seg_per_min, 12), 1, 120)),
        max_concurrent_transcribes=int(_clamp(_as_int(max_concurrent, 2), 1, 8)),
        provider=_normalize_provider(provider),
        timeout_seconds=_clamp(_as_float(timeout_s, 20.0), 1.0, 120.0),
        language_code=_safe_token(language_code, "ru", 16),
        model_id=_safe_token(model_id, "", 80),
        cache_enabled=bool(cache_enabled),
        cache_max_entries=int(_clamp(_as_int(cache_max_entries, 512), 0, 5000)),
        max_audio_seconds=_clamp(_as_float(max_audio_s, 12.0), 1.0, 60.0),
        max_wav_bytes=int(_clamp(_as_int(max_wav_bytes, 1048576), 65536, 16777216)),
        max_provider_calls_per_meeting=int(_clamp(_as_int(max_calls, 60), 0, 1000)),
        max_provider_audio_seconds_per_meeting=_clamp(_as_float(max_audio_per_meeting, 300.0), 0.0, 7200.0),
        overrides_applied=applied,
    )
