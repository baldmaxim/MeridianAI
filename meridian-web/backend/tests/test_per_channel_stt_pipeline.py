"""Per-channel STT pipeline (Этап 17): segmentation/VAD/dominance + fake STT adapter."""

import array

from app.core.context.audio_frame_v2 import build_audio_frame_v2, parse_audio_frame_v2
from app.core.context.per_channel_stt_policy import PerChannelSttRuntimeConfig
from app.core.audio.per_channel_stt import (
    NoopPerChannelSttAdapter,
    PerChannelSttPipeline,
    pcm16_mono_to_wav_bytes,
)
from app.core.audio.per_channel_stt_adapter import PerChannelSttAdapterResult, hash_text


class FakeAdapter:
    """Provider-адаптер с новым интерфейсом transcribe_segment(segment, config) (Этап 18)."""
    provider = "fake"

    def __init__(self, text="дайте лучше условия", conf=None, error_kind=None):
        self._text, self._conf, self._error = text, conf, error_kind
        self.calls = 0

    async def transcribe_segment(self, segment, config):
        self.calls += 1
        if self._error:
            return PerChannelSttAdapterResult(provider="fake", error_kind=self._error)
        return PerChannelSttAdapterResult(text=self._text, text_hash=hash_text(self._text),
                                          confidence=self._conf, provider="fake", latency_ms=5)


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


def _frame(seq, a0, a1, frames=1600, channels=2, created=0):
    samples = []
    for _ in range(frames):
        samples += [a0, a1][:channels]
    h = dict(protocol_version=2, sequence=seq, sample_rate=16000, channels=channels, codec="pcm16",
             layout="interleaved", route="usb_recorder", capture_pipeline="multichannel_shadow_stream",
             frame_duration_ms=100, created_at_ms=created)
    return parse_audio_frame_v2(build_audio_frame_v2(h, array.array("h", samples).tobytes()))


def _drive(pipe, loud_frames=5, a0=8000, a1=40, silence=3):
    segs = []
    for i in range(loud_frames):
        segs += pipe.ingest_frame(_frame(i, a0, a1, created=1000 + i * 100))
    for i in range(loud_frames, loud_frames + silence):
        segs += pipe.ingest_frame(_frame(i, 25, 25))
    return segs


def test_split_and_dominance_segment():
    pipe = PerChannelSttPipeline(_cfg(), FakeAdapter())
    segs = _drive(pipe)
    assert len(segs) == 1
    seg = segs[0]
    assert seg.channel_index == 0           # ch0 dominant
    assert seg.source_id == "channel_0"
    assert seg.channel_label == "channel_0"
    assert seg.dominance > 0.9
    assert seg.duration_ms >= 200


def test_low_rms_no_segment():
    pipe = PerChannelSttPipeline(_cfg(min_rms=0.5), FakeAdapter())  # порог недостижим
    segs = _drive(pipe, a0=200, a1=10)
    assert segs == []
    assert pipe.get_stats().segment_started_count == 0


def test_low_dominance_drop():
    # оба канала равны → dominance ~0.5 < 0.55 → не активен, сегмент не стартует
    pipe = PerChannelSttPipeline(_cfg(), FakeAdapter())
    segs = _drive(pipe, a0=4000, a1=4000)
    assert segs == []


def test_segment_finalizes_after_silence():
    pipe = PerChannelSttPipeline(_cfg(end_silence_ms=200), FakeAdapter())
    segs = _drive(pipe, loud_frames=4, silence=3)
    assert len(segs) == 1


def test_max_segment_force_finalize():
    pipe = PerChannelSttPipeline(_cfg(max_segment_ms=300), FakeAdapter())
    # непрерывно активный ch0 → форс-финализация по max_segment_ms (300мс ~ 3 кадра)
    segs = []
    for i in range(10):
        segs += pipe.ingest_frame(_frame(i, 8000, 40, created=1000 + i * 100))
    assert len(segs) >= 2  # несколько форс-финализаций


def test_rate_limit_drop():
    pipe = PerChannelSttPipeline(_cfg(max_segments_per_minute=1, end_silence_ms=200), FakeAdapter())
    # два отдельных сегмента в пределах минуты → второй дропается по rate limit
    out = []
    for blk in range(2):
        for i in range(4):
            out += pipe.ingest_frame(_frame(blk * 100 + i, 8000, 40, created=1000 + (blk * 1000) + i * 100))
        for i in range(3):
            out += pipe.ingest_frame(_frame(blk * 100 + 50 + i, 25, 25, created=2000 + blk * 1000 + i * 100))
    assert len(out) == 1
    assert pipe.get_stats().segment_dropped_rate_limit_count >= 1


async def test_transcribe_success_creates_candidate():
    pipe = PerChannelSttPipeline(_cfg(), FakeAdapter())
    seg = _drive(pipe)[0]
    cand = await pipe.transcribe_segment(seg)
    assert cand is not None
    assert cand.audio_source_id == "channel_0"
    assert cand.source_kind == "multi_channel"
    assert cand.attribution_source == "multi_source_segment"
    assert cand.source == "per_channel_stt"
    payload = pipe.segment_to_source_candidate_payload(cand)
    assert payload["candidate_pipeline"] == "per_channel_stt"
    assert "side" not in payload and "speaker_side" not in payload  # НЕ сторона


async def test_attribution_confidence_capped():
    pipe = PerChannelSttPipeline(_cfg(), FakeAdapter(conf=1.0))
    seg = _drive(pipe)[0]
    cand = await pipe.transcribe_segment(seg)
    assert cand.attribution_confidence <= 0.85


async def test_min_text_chars_drops_candidate():
    pipe = PerChannelSttPipeline(_cfg(min_text_chars=50), FakeAdapter(text="ок"))
    seg = _drive(pipe)[0]
    cand = await pipe.transcribe_segment(seg)
    assert cand is None
    assert pipe.get_stats().transcribe_success_count == 1  # транскрипция была, но текст короткий


async def test_noop_adapter_unavailable():
    pipe = PerChannelSttPipeline(_cfg(provider="noop"), NoopPerChannelSttAdapter())
    seg = _drive(pipe)[0]
    cand = await pipe.transcribe_segment(seg)
    assert cand is None
    st = pipe.get_stats()
    assert st.last_error_kind == "adapter_unavailable"
    assert st.adapter_unavailable_count == 1


# --- Stage 18: provider/cache/budget ---

async def test_cache_hit_avoids_second_provider_call():
    adapter = FakeAdapter()
    pipe = PerChannelSttPipeline(_cfg(), adapter)
    seg = _drive(pipe)[0]
    c1 = await pipe.transcribe_segment(seg)
    c2 = await pipe.transcribe_segment(seg)  # тот же сегмент → cache hit
    assert c1 is not None and c2 is not None
    assert adapter.calls == 1                       # провайдер вызван один раз
    st = pipe.get_stats()
    assert st.transcribe_cache_hit_count == 1
    assert st.transcribe_success_count == 1


async def test_budget_exhausted_prevents_provider_call():
    adapter = FakeAdapter()
    pipe = PerChannelSttPipeline(_cfg(max_provider_calls_per_meeting=0), adapter)
    seg = _drive(pipe)[0]
    cand = await pipe.transcribe_segment(seg)
    assert cand is None
    assert adapter.calls == 0
    assert pipe.get_stats().transcribe_budget_exhausted_count == 1
    assert pipe.get_stats().last_error_kind == "budget_exhausted"


async def test_noop_adapter_does_not_consume_budget():
    # provider=noop (нет внешнего вызова) → budget не тратится даже при max_calls=0
    pipe = PerChannelSttPipeline(_cfg(provider="noop", max_provider_calls_per_meeting=0),
                                 NoopPerChannelSttAdapter())
    seg = _drive(pipe)[0]
    cand = await pipe.transcribe_segment(seg)
    assert cand is None
    st = pipe.get_stats()
    assert st.transcribe_budget_exhausted_count == 0   # бюджет не тронут
    assert st.adapter_unavailable_count == 1           # noop → adapter_unavailable
    assert pipe._budget.calls_used == 0


async def test_cache_hit_does_not_consume_budget():
    adapter = FakeAdapter()
    pipe = PerChannelSttPipeline(_cfg(max_provider_calls_per_meeting=1), adapter)
    seg = _drive(pipe)[0]
    await pipe.transcribe_segment(seg)      # miss → 1 provider call, budget consumed (1/1)
    assert pipe._budget.calls_used == 1
    c2 = await pipe.transcribe_segment(seg)  # hit → не тратит budget, не зовёт провайдер
    assert c2 is not None
    assert adapter.calls == 1
    assert pipe._budget.calls_used == 1     # бюджет не увеличился на cache hit
    assert pipe.get_stats().transcribe_budget_exhausted_count == 0


async def test_max_audio_seconds_drops_segment():
    adapter = FakeAdapter()
    pipe = PerChannelSttPipeline(_cfg(max_audio_seconds=0.1), adapter)  # 100мс лимит < 500мс сегмент
    seg = _drive(pipe)[0]
    cand = await pipe.transcribe_segment(seg)
    assert cand is None
    assert adapter.calls == 0
    assert pipe.get_stats().transcribe_audio_too_long_count == 1


async def test_adapter_error_kinds_mapped_to_stats():
    for ek, attr in [("timeout", "transcribe_timeout_count"),
                     ("empty_text", "transcribe_empty_text_count"),
                     ("provider_error", "transcribe_provider_error_count"),
                     ("audio_too_large", "transcribe_audio_too_large_count"),
                     ("api_key_missing", "adapter_unavailable_count")]:
        pipe = PerChannelSttPipeline(_cfg(), FakeAdapter(error_kind=ek))
        seg = _drive(pipe)[0]
        cand = await pipe.transcribe_segment(seg)
        assert cand is None
        assert getattr(pipe.get_stats(), attr) == 1
        assert pipe.get_stats().last_error_kind == ek


async def test_provider_confidence_influences_candidate():
    seg_a = _drive(PerChannelSttPipeline(_cfg(), FakeAdapter()))[0]
    c_low = await PerChannelSttPipeline(_cfg(), FakeAdapter(conf=0.0)).transcribe_segment(seg_a)
    c_high = await PerChannelSttPipeline(_cfg(), FakeAdapter(conf=1.0)).transcribe_segment(seg_a)
    assert c_high.attribution_confidence > c_low.attribution_confidence
    assert c_high.attribution_confidence <= 0.85


async def test_candidate_text_not_in_stats():
    pipe = PerChannelSttPipeline(_cfg(), FakeAdapter(text="секретная реплика"))
    seg = _drive(pipe)[0]
    await pipe.transcribe_segment(seg)
    assert "секретная" not in pipe.get_stats().model_dump_json()


def test_no_raw_text_or_audio_in_stats_repr():
    pipe = PerChannelSttPipeline(_cfg(), FakeAdapter())
    seg = _drive(pipe)[0]
    r = repr(seg)
    assert "pcm_bytes=" in r          # только размер payload
    assert "8000" not in r            # raw PCM-семплы не в repr
    assert "\\x" not in r
    blob = pipe.get_stats().model_dump_json()
    assert "дайте" not in blob        # stats без raw text


def test_pcm16_to_wav_helper():
    wav = pcm16_mono_to_wav_bytes(array.array("h", [100, -100] * 100).tobytes(), 16000)
    assert wav[:4] == b"RIFF" and b"WAVE" in wav[:16]


def test_clear_resets():
    pipe = PerChannelSttPipeline(_cfg(), FakeAdapter())
    _drive(pipe)
    pipe.clear()
    st = pipe.get_stats()
    assert st.frame_count == 0 and st.segment_finalized_count == 0
