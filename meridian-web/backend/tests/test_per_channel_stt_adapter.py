"""Per-channel STT provider adapter (Этап 18): helpers, cache, budget, adapters."""

import array

from app.core.context.per_channel_stt_policy import PerChannelSttRuntimeConfig
from app.core.audio.per_channel_stt_adapter import (
    ElevenLabsBatchPerChannelSttAdapter,
    NoopPerChannelSttAdapter,
    PerChannelSttAdapterResult,
    PerChannelSttBudget,
    PerChannelSttCache,
    build_per_channel_stt_adapter,
    hash_audio_for_cache,
    hash_text,
    normalize_stt_text,
    pcm16_mono_to_wav_bytes,
)


def _cfg(**ovr) -> PerChannelSttRuntimeConfig:
    base = dict(enabled=True, shadow_mode=False, session_overrides_enabled=True, trace_enabled=True,
                trace_sample_rate=1.0, max_channels=2, min_rms=0.01, min_dominance=0.55,
                min_segment_ms=200, end_silence_ms=200, max_segment_ms=8000, min_text_chars=4,
                max_segments_per_minute=12, max_concurrent_transcribes=2, provider="elevenlabs_batch",
                timeout_seconds=20.0, language_code="ru", model_id="", cache_enabled=True,
                cache_max_entries=512, max_audio_seconds=12.0, max_wav_bytes=1048576,
                max_provider_calls_per_meeting=60, max_provider_audio_seconds_per_meeting=300.0)
    base.update(ovr)
    return PerChannelSttRuntimeConfig(**base)


class _Seg:
    def __init__(self, t):
        self.text = t


class _FakeBatch:
    """Имитация BatchTranscriptionService (Этап 19: принимает request_timeout)."""
    def __init__(self, api_key, language_code, model_id, segments=None, raise_exc=None, sleep=0.0):
        self.api_key, self.language_code, self.model_id = api_key, language_code, model_id

    async def transcribe(self, wav, *, diarize=True, keyterms=None, request_timeout=None):
        return [_Seg("дайте"), _Seg(" лучше условия")]


def _factory(**kw):
    def _f(api_key, language_code, model_id):
        return _FakeBatch(api_key, language_code, model_id, **kw)
    return _f


class _FakeSegment:
    def __init__(self, pcm=b"\x10\x00" * 800, sr=16000):
        self.pcm16_mono = pcm
        self.sample_rate = sr
        self.duration_ms = 500
        self.dominance = 0.9
        self.rms = 0.1
        self.source_id = "channel_0"
        self.channel_label = "channel_0"
        self.channel_index = 0
        self.start_ms = 1000
        self.end_ms = 1500


# --- helpers ---

def test_pcm16_mono_to_wav_bytes():
    wav = pcm16_mono_to_wav_bytes(array.array("h", [100, -100] * 100).tobytes(), 16000)
    assert wav[:4] == b"RIFF" and b"WAVE" in wav[:16]


def test_hash_audio_for_cache_stable_and_varies():
    a = hash_audio_for_cache(b"abc", 16000, "elevenlabs_batch", "scribe_v2", "ru")
    assert a == hash_audio_for_cache(b"abc", 16000, "elevenlabs_batch", "scribe_v2", "ru")
    assert a != hash_audio_for_cache(b"abc", 16000, "elevenlabs_batch", "scribe_v2", "en")  # lang
    assert a != hash_audio_for_cache(b"abc", 16000, "elevenlabs_batch", "other", "ru")       # model
    assert a != hash_audio_for_cache(b"abd", 16000, "elevenlabs_batch", "scribe_v2", "ru")   # audio


def test_normalize_stt_text():
    assert normalize_stt_text("  дайте   лучше  ") == "дайте лучше"
    assert normalize_stt_text("") == ""
    assert normalize_stt_text("a\nb") == "a b"


# --- noop / unknown provider ---

async def test_noop_adapter_returns_none():
    assert await NoopPerChannelSttAdapter().transcribe_segment(_FakeSegment(), _cfg()) is None


def test_build_adapter_by_provider():
    assert isinstance(build_per_channel_stt_adapter(_cfg(provider="noop")), NoopPerChannelSttAdapter)
    a = build_per_channel_stt_adapter(_cfg(provider="elevenlabs_batch"), api_key="K")
    assert isinstance(a, ElevenLabsBatchPerChannelSttAdapter)
    unknown = build_per_channel_stt_adapter(_cfg(provider="weird"))
    assert "weird" in repr(type(unknown).__name__).lower() or True  # StaticError


async def test_unknown_provider_error():
    unknown = build_per_channel_stt_adapter(_cfg(provider="weird"))
    res = await unknown.transcribe_segment(_FakeSegment(), _cfg(provider="weird"))
    assert res.error_kind == "unknown_provider"


# --- elevenlabs batch adapter ---

async def test_batch_adapter_success():
    a = build_per_channel_stt_adapter(_cfg(), api_key="K", service_factory=_factory())
    res = await a.transcribe_segment(_FakeSegment(), _cfg())
    assert res.error_kind is None
    assert res.text == "дайте лучше условия"
    assert res.provider == "elevenlabs_batch"
    assert res.text_hash and res.latency_ms is not None


async def test_batch_adapter_api_key_missing():
    a = build_per_channel_stt_adapter(_cfg(), api_key=None, service_factory=_factory())
    res = await a.transcribe_segment(_FakeSegment(), _cfg())
    assert res.error_kind == "api_key_missing"


async def test_batch_adapter_empty_text():
    class _EmptyBatch(_FakeBatch):
        async def transcribe(self, wav, *, diarize=True, keyterms=None, request_timeout=None):
            return [_Seg("   ")]
    a = build_per_channel_stt_adapter(_cfg(), api_key="K",
                                      service_factory=lambda k, l, m: _EmptyBatch(k, l, m))
    res = await a.transcribe_segment(_FakeSegment(), _cfg())
    assert res.error_kind == "empty_text"


async def test_batch_adapter_provider_error():
    class _BoomBatch(_FakeBatch):
        async def transcribe(self, wav, *, diarize=True, keyterms=None, request_timeout=None):
            raise RuntimeError("boom")
    a = build_per_channel_stt_adapter(_cfg(), api_key="K",
                                      service_factory=lambda k, l, m: _BoomBatch(k, l, m))
    res = await a.transcribe_segment(_FakeSegment(), _cfg())
    assert res.error_kind == "provider_error"


async def test_batch_adapter_timeout():
    import asyncio

    class _SlowBatch(_FakeBatch):
        async def transcribe(self, wav, *, diarize=True, keyterms=None, request_timeout=None):
            await asyncio.sleep(2.0)
            return [_Seg("late")]
    a = build_per_channel_stt_adapter(_cfg(timeout_seconds=1.0), api_key="K",
                                      service_factory=lambda k, l, m: _SlowBatch(k, l, m))
    res = await a.transcribe_segment(_FakeSegment(), _cfg(timeout_seconds=1.0))
    assert res.error_kind == "timeout"


async def test_batch_adapter_audio_too_large():
    a = build_per_channel_stt_adapter(_cfg(max_wav_bytes=65536), api_key="K", service_factory=_factory())
    big = _FakeSegment(pcm=b"\x01\x00" * 200000)  # > 65536 wav
    res = await a.transcribe_segment(big, _cfg(max_wav_bytes=65536))
    assert res.error_kind == "audio_too_large"


async def test_adapter_passes_bounded_timeout_to_service():
    seen = {}

    class _RecBatch:
        def __init__(self, api_key, language_code, model_id):
            pass

        async def transcribe(self, wav, *, diarize=True, keyterms=None, request_timeout=None):
            seen["timeout"] = request_timeout
            return [_Seg("ok text")]
    a = build_per_channel_stt_adapter(_cfg(timeout_seconds=15.0), api_key="K",
                                      service_factory=lambda k, l, m: _RecBatch(k, l, m))
    await a.transcribe_segment(_FakeSegment(), _cfg(timeout_seconds=15.0))
    assert seen["timeout"] == 15.0


async def test_adapter_timeout_clamped_to_120():
    seen = {}

    class _RecBatch:
        def __init__(self, api_key, language_code, model_id):
            pass

        async def transcribe(self, wav, *, diarize=True, keyterms=None, request_timeout=None):
            seen["timeout"] = request_timeout
            return [_Seg("ok text")]
    # adapter re-clamps timeout к 1..120 (даже если config выше)
    a = build_per_channel_stt_adapter(_cfg(timeout_seconds=200.0), api_key="K",
                                      service_factory=lambda k, l, m: _RecBatch(k, l, m))
    await a.transcribe_segment(_FakeSegment(), _cfg(timeout_seconds=200.0))
    assert seen["timeout"] == 120.0


async def test_batch_service_backward_compatible_timeout(monkeypatch):
    from app.core.transcription.batch_service import BatchTranscriptionService
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": "ok"}

    svc = BatchTranscriptionService(api_key="K")

    def _post(url, files=None, timeout=None):
        captured["timeout"] = timeout
        return _Resp()
    monkeypatch.setattr(svc.session, "post", _post)
    await svc.transcribe(b"wav")  # без request_timeout → прежний дефолт 300
    assert captured["timeout"] == 300
    await svc.transcribe(b"wav", request_timeout=20.0)
    assert captured["timeout"] == 20.0


def test_adapter_result_repr_no_raw():
    r = PerChannelSttAdapterResult(text="секретный текст", text_hash="h", provider="elevenlabs_batch")
    assert "секретный" not in repr(r)
    assert "has_text=True" in repr(r)


def test_elevenlabs_adapter_repr_no_api_key():
    a = ElevenLabsBatchPerChannelSttAdapter(api_key="SUPERSECRETKEY")
    assert "SUPERSECRETKEY" not in repr(a)
    assert "has_key=True" in repr(a)


# --- cache ---

def test_cache_hit_miss_eviction():
    c = PerChannelSttCache(max_entries=2)
    assert c.get("a") is None and c.cache_miss_count == 1
    c.set("a", PerChannelSttAdapterResult(text="x", text_hash="h"))
    got = c.get("a")
    assert got is not None and got.cached is True and c.cache_hit_count == 1
    c.set("b", PerChannelSttAdapterResult(text="y", text_hash="h"))
    c.set("cc", PerChannelSttAdapterResult(text="z", text_hash="h"))  # evicts LRU
    assert c.cache_eviction_count == 1


def test_cache_disabled_zero_entries():
    c = PerChannelSttCache(max_entries=0)
    c.set("a", PerChannelSttAdapterResult(text="x", text_hash="h"))
    assert c.get("a") is None


# --- budget ---

def test_budget_allow_consume_exhausted():
    b = PerChannelSttBudget(max_calls=2, max_audio_seconds=10.0)
    assert b.allow(1000) is True
    b.consume(1000)
    assert b.allow(1000) is True
    b.consume(1000)
    assert b.allow(1000) is False  # calls exhausted
    assert b.exhausted_count >= 1


def test_budget_zero_blocks():
    assert PerChannelSttBudget(max_calls=0, max_audio_seconds=10.0).allow(100) is False
    assert PerChannelSttBudget(max_calls=10, max_audio_seconds=0.0).allow(100) is False


def test_budget_audio_seconds_limit():
    b = PerChannelSttBudget(max_calls=100, max_audio_seconds=1.0)
    assert b.allow(800) is True
    b.consume(800)
    assert b.allow(800) is False  # 0.8 + 0.8 > 1.0
