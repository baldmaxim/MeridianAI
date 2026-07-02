"""Signal Engine trace (Этап 2): безопасный structured trace без утечки текста."""

import json

from app.core.context.signal_engine import NegotiationSignal, SignalEngineResult
from app.core.context.signal_policy import SignalRuntimeConfig, evaluate_signal_decision
from app.core.context.signal_trace import (
    build_signal_trace_event,
    log_signal_trace,
    make_text_hash,
    safe_preview,
)
from app.core.context.speaker_identity import SpeakerIdentity, build_speaker_identity_map


class _CapLogger:
    """Захватывает отформатированные строки logger.info."""

    def __init__(self):
        self.lines = []

    def info(self, msg, *args):
        self.lines.append(msg % args if args else msg)


def _cfg(**kw) -> SignalRuntimeConfig:
    base = dict(
        enabled=True, shadow_mode=True, allow_legacy_fallback=True,
        min_confidence=0.55, min_actionability=0.55, min_urgency=0.45,
    )
    base.update(kw)
    return SignalRuntimeConfig(**base)


def _strong() -> NegotiationSignal:
    return NegotiationSignal(
        should_prompt=True, situation_type="price_pressure",
        confidence=0.8, actionability=0.7, urgency=0.6,
        recommended_card_types=["counter"],
        novelty_key="price_pressure:counterparty:x",
    )


_RECENT = "[00:01] НЕ МЫ: дайте скидку, пишите на ivan@example.com"
_CURRENT = "звоните +7 999 123 45 67 по поводу цены"
_DOC = "DOCSECRET содержимое договора пункт 4.2 ответственность"


def _build(include_text, result=None):
    sig = _strong()
    result = result or SignalEngineResult(signal=sig, raw_response="RAWSECRET_RESPONSE")
    decision = evaluate_signal_decision(sig, result, _cfg())
    return build_signal_trace_event(
        check_id="abc123", result=result, decision=decision, shadow_mode=True,
        recent_dialog=_RECENT, current_text=_CURRENT, document_context=_DOC,
        session_id=7, meeting_id=42, source_method="debounced_hint_check",
        latency_ms=120, include_text=include_text,
    )


def test_trace_no_text_when_include_text_false():
    event = _build(include_text=False)
    assert event.current_text_preview is None
    assert event.recent_dialog_preview is None
    # длины и hash присутствуют
    assert event.current_text_chars == len(_CURRENT)
    assert event.recent_dialog_chars == len(_RECENT)
    assert event.document_context_chars == len(_DOC)
    assert event.text_hash and len(event.text_hash) >= 12
    # сериализация не содержит фрагментов переговоров
    payload = json.dumps(event.model_dump(), ensure_ascii=False)
    assert "скидку" not in payload
    assert "цены" not in payload
    assert "DOCSECRET" not in payload


def test_trace_audio_capture_safe_fields_present():
    from app.core.context.audio_capture_metadata import parse_audio_capture_metadata
    sig = _strong()
    result = SignalEngineResult(signal=sig)
    decision = evaluate_signal_decision(sig, result, _cfg())
    meta = parse_audio_capture_metadata({
        "route": "usb_recorder", "capturePipeline": "stereo_requested_mono_stream",
        "deviceLabel": "Zoom H2n SECRETLABEL", "deviceId": "SECRETID",
        "actualChannelCount": 1, "actualSampleRate": 16000})
    event = build_signal_trace_event(
        check_id="c", result=result, decision=decision, shadow_mode=True,
        audio_capture_metadata=meta)
    assert event.audio_capture_route == "usb_recorder"
    assert event.audio_capture_pipeline == "stereo_requested_mono_stream"
    assert event.audio_capture_actual_channel_count == 1
    assert event.audio_capture_actual_sample_rate == 16000
    assert event.audio_capture_source_kind == "usb_recorder"
    assert event.audio_capture_source_is_isolated is False
    # SIGNAL_ENGINE_TRACE НЕ содержит raw label/id И НЕ содержит device hashes
    payload = json.dumps(event.model_dump(), ensure_ascii=False)
    assert "Zoom H2n" not in payload and "SECRETLABEL" not in payload and "SECRETID" not in payload
    assert meta.device_label_hash not in payload
    assert meta.device_id_hash not in payload


def test_trace_audio_capture_absent_when_no_metadata():
    event = _build(include_text=False)
    assert event.audio_capture_route is None
    assert event.audio_capture_pipeline is None
    assert event.audio_capture_source_kind is None


def test_trace_multichannel_safe_fields_present():
    import array
    from app.core.context.audio_frame_v2 import build_audio_frame_v2
    from app.core.context.multichannel_shadow_state import AudioMultichannelShadowIngest
    ing = AudioMultichannelShadowIngest()
    h = dict(protocol_version=2, sequence=1, sample_rate=16000, channels=2, codec="pcm16",
             layout="interleaved", route="usb_recorder", capture_pipeline="multichannel_shadow_stream")
    ing.ingest_frame(build_audio_frame_v2(h, array.array("h", (12345, -9999, 4242, -4242)).tobytes()))
    stats = ing.get_stats(enabled=True)
    sig = _strong(); result = SignalEngineResult(signal=sig)
    decision = evaluate_signal_decision(sig, result, _cfg())
    event = build_signal_trace_event(
        check_id="c", result=result, decision=decision, shadow_mode=True,
        multichannel_shadow_stats=stats)
    assert event.audio_multichannel_shadow_enabled is True
    assert event.audio_multichannel_frame_count == 1
    assert event.audio_multichannel_max_channels_seen == 2
    assert event.audio_multichannel_last_channels == 2
    # trace НЕ содержит raw PCM / payload / source ids
    payload = json.dumps(event.model_dump(), ensure_ascii=False, default=str)
    assert "12345" not in payload and "payload" not in payload


def test_trace_multichannel_absent_when_no_stats():
    event = _build(include_text=False)
    assert event.audio_multichannel_shadow_enabled is None
    assert event.audio_multichannel_frame_count is None
    assert event.audio_multichannel_max_channels_seen is None


def test_trace_per_channel_stt_safe_fields_present():
    from app.core.audio.per_channel_stt import PerChannelSttStats
    stats = PerChannelSttStats(enabled=True, shadow_mode=True, segment_finalized_count=3,
                               transcribe_success_count=3, candidate_shadow_suppressed_count=3,
                               candidate_emit_count=0, average_dominance=0.81)
    sig = _strong(); result = SignalEngineResult(signal=sig)
    decision = evaluate_signal_decision(sig, result, _cfg())
    event = build_signal_trace_event(check_id="c", result=result, decision=decision, shadow_mode=True,
                                     per_channel_stt_stats=stats)
    assert event.audio_per_channel_stt_enabled is True
    assert event.audio_per_channel_stt_segment_finalized_count == 3
    assert event.audio_per_channel_stt_candidate_shadow_suppressed_count == 3
    assert event.audio_per_channel_stt_average_dominance == 0.81
    # trace без raw source ids/channel labels/transcript (имена полей audio_per_channel_stt_* — не утечка)
    payload = json.dumps(event.model_dump(), ensure_ascii=False, default=str)
    assert "channel_0" not in payload  # raw channel label
    assert "track_2" not in payload    # raw track/source id
    assert "дайте" not in payload      # raw transcript


def test_trace_per_channel_stt_absent_when_no_stats():
    event = _build(include_text=False)
    assert event.audio_per_channel_stt_enabled is None
    assert event.audio_per_channel_stt_segment_finalized_count is None


def test_trace_preview_present_and_truncated_when_include_text_true():
    event = _build(include_text=True)
    assert event.current_text_preview is not None
    assert event.recent_dialog_preview is not None
    # document_context НЕ превьюится даже при include_text=true
    payload = json.dumps(event.model_dump(), ensure_ascii=False)
    assert "DOCSECRET" not in payload

    long_event = build_signal_trace_event(
        check_id="x", result=SignalEngineResult(signal=_strong()),
        decision=evaluate_signal_decision(_strong(), SignalEngineResult(signal=_strong()), _cfg()),
        shadow_mode=True, current_text="a" * 1000, recent_dialog="", document_context="",
        include_text=True, preview_max_chars=300,
    )
    assert len(long_event.current_text_preview) <= 300


def test_safe_preview_masks_email_and_phone():
    out = safe_preview("mail ivan@example.com phone +7 999 123 45 67 done")
    assert "ivan@example.com" not in out
    assert "[email]" in out
    assert "[phone]" in out
    assert "999 123" not in out


def test_safe_preview_collapses_newlines():
    out = safe_preview("line1\n\nline2\tend")
    assert "\n" not in out
    assert "line1 line2 end" == out


def test_make_text_hash_stable():
    assert make_text_hash("foo") == make_text_hash("foo")
    assert make_text_hash("foo") != make_text_hash("bar")
    assert make_text_hash("") == make_text_hash("")


def test_log_signal_trace_no_raw_response_or_full_document():
    result = SignalEngineResult(signal=_strong(), raw_response="RAWSECRET_RESPONSE")
    decision = evaluate_signal_decision(_strong(), result, _cfg())
    event = build_signal_trace_event(
        check_id="abc123", result=result, decision=decision, shadow_mode=True,
        recent_dialog=_RECENT, current_text=_CURRENT, document_context=_DOC,
        include_text=False,
    )
    log = _CapLogger()
    log_signal_trace(log, event)
    assert len(log.lines) == 1
    line = log.lines[0]
    assert line.startswith("SIGNAL_ENGINE_TRACE {")
    assert "RAWSECRET_RESPONSE" not in line
    assert "DOCSECRET" not in line
    assert "скидку" not in line
    # это валидный JSON после префикса
    payload = line[len("SIGNAL_ENGINE_TRACE "):]
    parsed = json.loads(payload)
    assert parsed["check_id"] == "abc123"
    assert parsed["situation_type"] == "price_pressure"
    assert parsed["error_kind"] == "none"


def _speaker_map():
    return build_speaker_identity_map([
        SpeakerIdentity(raw_speaker_label="SM_0", display_name="Иван Петров",
                        organization="ООО Ромашка", side="our_side",
                        confidence=0.9, source="manual_correction"),
        SpeakerIdentity(raw_speaker_label="SM_1", side="counterparty",
                        confidence=0.85, source="legacy_role"),
        SpeakerIdentity(raw_speaker_label="SM_2", side="unknown",
                        confidence=0.0, source="transcript_label"),
    ])


def test_trace_speaker_aggregates_present():
    sig = _strong()
    result = SignalEngineResult(signal=sig)
    decision = evaluate_signal_decision(sig, result, _cfg())
    event = build_signal_trace_event(
        check_id="sp1", result=result, decision=decision, shadow_mode=True,
        recent_dialog="", current_text="x", document_context="",
        include_text=False,
        speaker_context="Speaker SM_0: side=our_side, ...", speaker_map=_speaker_map(),
    )
    assert event.speaker_side_counts == {"our_side": 1, "counterparty": 1, "unknown": 1}
    assert event.speaker_sources == {"manual_correction": 1, "legacy_role": 1, "transcript_label": 1}
    assert event.speaker_average_confidence is not None
    assert event.speaker_context_chars > 0
    # Этап 5: счётчики
    assert event.speaker_count == 3
    assert event.speaker_unknown_side_count == 1
    assert event.speaker_hint_source_count == 1  # только manual_correction с conf>0


def test_trace_attribution_aggregates_present_and_no_leak():
    from app.core.context.speaker_audio_attribution import SpeakerAudioAttributionTracker
    t = SpeakerAudioAttributionTracker()
    t.observe({"speaker_label": "SM_0", "audio_source_id": "secondary",
               "attribution_confidence": 0.9, "source_is_isolated": True})
    t.observe({"speaker_label": "SM_1", "audio_source_id": "primary", "attribution_confidence": 0.4})
    sig = _strong()
    result = SignalEngineResult(signal=sig)
    decision = evaluate_signal_decision(sig, result, _cfg())
    event = build_signal_trace_event(
        check_id="attr1", result=result, decision=decision, shadow_mode=True,
        recent_dialog="", current_text="x", document_context="",
        include_text=False, attribution_stats=t.get_stats(),
    )
    assert event.speaker_audio_attribution_observation_count == 2
    assert event.speaker_audio_attribution_stable_link_count == 1
    assert event.speaker_audio_attribution_ambiguous_count == 0
    assert isinstance(event.speaker_audio_attribution_sources, dict)
    payload = json.dumps(event.model_dump(), ensure_ascii=False)
    for leak in ("SM_0", "SM_1", "secondary", "primary"):
        assert leak not in payload


def test_trace_source_reconcile_aggregates_present_and_no_leak():
    from app.core.context.source_attribution_reconciler import SourceAttributionReconciler
    r = SourceAttributionReconciler()
    r.observe_candidate({"text": "дайте лучше условия", "start_ms": 1000, "end_ms": 3000,
                         "audio_source_id": "secondary", "source_is_isolated": True,
                         "source_kind": "multi_channel", "attribution_source": "multi_source_segment",
                         "attribution_confidence": 0.8, "candidate_pipeline": "multi_channel_live"})
    r.reconcile_segment({"speaker_label": "SM_1", "segment_id": "s1", "text": "дайте лучше условия",
                         "start_ms": 1100, "end_ms": 2900})
    sig = _strong()
    result = SignalEngineResult(signal=sig)
    decision = evaluate_signal_decision(sig, result, _cfg())
    event = build_signal_trace_event(
        check_id="rc1", result=result, decision=decision, shadow_mode=True,
        recent_dialog="", current_text="x", document_context="",
        include_text=False, source_reconcile_stats=r.get_stats())
    assert event.source_reconcile_candidate_count == 1
    assert event.source_reconcile_match_count == 1
    assert isinstance(event.source_reconcile_match_reasons, dict)
    payload = json.dumps(event.model_dump(), ensure_ascii=False)
    for leak in ("SM_1", "secondary", "дайте", "s1"):
        assert leak not in payload


def test_trace_audio_link_aggregates_present_and_no_leak():
    from app.core.context.speaker_audio_links import extract_audio_links_from_metadata
    alm = extract_audio_links_from_metadata(
        audio_source_metadata={"SM_0": "primary", "SM_1": "secondary"},
        channel_metadata={"SM_0": "left"},
    )
    sig = _strong()
    result = SignalEngineResult(signal=sig)
    decision = evaluate_signal_decision(sig, result, _cfg())
    event = build_signal_trace_event(
        check_id="al1", result=result, decision=decision, shadow_mode=True,
        recent_dialog="", current_text="x", document_context="",
        include_text=False, speaker_map=_speaker_map(), audio_link_map=alm,
    )
    assert event.speaker_audio_linked_count == 2
    assert event.speaker_channel_linked_count == 1
    assert event.speaker_audio_link_average_confidence is not None
    assert isinstance(event.speaker_audio_link_sources, dict)
    # no raw source ids / channel labels / speaker labels in serialized trace
    payload = json.dumps(event.model_dump(), ensure_ascii=False)
    for leak in ("primary", "secondary", "left", "right", "SM_0", "SM_1"):
        assert leak not in payload


def test_trace_speaker_aggregates_no_names_or_labels():
    event = build_signal_trace_event(
        check_id="sp2", result=SignalEngineResult(signal=_strong()),
        decision=evaluate_signal_decision(_strong(), SignalEngineResult(signal=_strong()), _cfg()),
        shadow_mode=True, recent_dialog="", current_text="x", document_context="",
        include_text=False,
        speaker_context="Speaker SM_0: side=our_side", speaker_map=_speaker_map(),
    )
    payload = json.dumps(event.model_dump(), ensure_ascii=False)
    # никаких имён/организаций/сырых меток в trace
    assert "Иван" not in payload
    assert "Ромашка" not in payload
    assert "SM_0" not in payload
    assert "SM_1" not in payload
