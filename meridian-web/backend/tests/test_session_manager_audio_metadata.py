"""Этап 6/7: SessionManager audio metadata + attribution (structured only, no DB)."""

from app.services.session_manager import SessionManager


def _by_label(link_map):
    return {lk.raw_speaker_label: lk for lk in link_map.links_by_stable_id.values()}


# --- Stage 6 backward compatibility: holders via setter ---

def test_set_speaker_audio_metadata_holders_become_link_map():
    sm = SessionManager(0)
    sm.set_speaker_audio_metadata(source_map={"SM_0": "primary"}, channel_map={"SM_0": "left"})
    lm = sm._collect_speaker_audio_metadata()
    assert lm is not None
    lk = _by_label(lm)["SM_0"]
    assert lk.audio_source_id == "primary"
    assert lk.channel_label == "left"


def test_collect_empty_returns_none():
    sm = SessionManager(0)
    assert sm._collect_speaker_audio_metadata() is None
    assert sm._collect_speaker_audio_metadata({"recent_dialog": "x"}) is None


# --- Stage 7: observe_speaker_audio_attribution + tracker → link map ---

def test_observe_accepts_structured_payload_and_creates_link_after_stable_obs():
    sm = SessionManager(0)
    # одно isolated high-confidence наблюдение → stable link
    n = sm.observe_speaker_audio_attribution(
        {"speaker_label": "SM_0", "audio_source_id": "secondary",
         "attribution_confidence": 0.9, "source_is_isolated": True})
    assert n == 1
    lm = sm._collect_speaker_audio_metadata()
    assert lm is not None
    assert _by_label(lm)["SM_0"].audio_source_id == "secondary"


def test_observe_ignores_text_only_fields():
    sm = SessionManager(0)
    n = sm.observe_speaker_audio_attribution(
        {"recent_dialog": "SM_0: дайте скидку", "document_context": "договор"})
    assert n == 0
    assert sm._collect_speaker_audio_metadata() is None


def test_observe_single_low_conf_room_mic_no_link():
    sm = SessionManager(0)
    sm.observe_speaker_audio_attribution(
        {"speaker_label": "SM_0", "audio_source_id": "primary", "attribution_confidence": 0.4})
    assert sm._collect_speaker_audio_metadata() is None  # no stable link


def test_collect_combines_holders_and_tracker():
    sm = SessionManager(0)
    sm.set_speaker_audio_metadata(source_map={"SM_9": "primary"})
    sm.observe_speaker_audio_attribution(
        {"speaker_label": "SM_0", "audio_source_id": "secondary",
         "attribution_confidence": 0.9, "source_is_isolated": True})
    lm = sm._collect_speaker_audio_metadata()
    byl = _by_label(lm)
    assert "SM_9" in byl  # holder
    assert "SM_0" in byl  # tracker


def test_collect_from_ctx_containers():
    sm = SessionManager(0)
    lm = sm._collect_speaker_audio_metadata({"speaker_sources": {"SM_0": "secondary"}})
    assert lm is not None
    assert _by_label(lm)["SM_0"].audio_source_id == "secondary"


# --- Stage 8: ctx segment observe (gated) + dedupe ---

def test_observe_safe_segment_payload_creates_link():
    sm = SessionManager(0)
    n = sm.observe_speaker_audio_attribution({
        "speaker_label": "SM_0", "audio_source_id": "secondary",
        "source_is_isolated": True, "attribution_confidence": 0.9,
        "source": "secondary_shadow", "segment_id": "seg-1"})
    assert n == 1
    lm = sm._collect_speaker_audio_metadata()
    assert _by_label(lm)["SM_0"].audio_source_id == "secondary"


def test_observe_unsafe_primary_room_metadata_ignored_via_segment_helper():
    # через build_observation_payload_from_segment (как ctx path) unsafe primary → no payload
    from app.core.context.segment_source_attribution import build_observation_payload_from_segment
    payload = build_observation_payload_from_segment({
        "speaker_label": "SM_0", "audio_source_id": "primary", "source_kind": "room_mic"})
    assert payload is None


def test_dedupe_prevents_double_observation_same_segment():
    sm = SessionManager(0)
    from app.core.context.segment_source_attribution import build_observation_payload_from_segment
    seg = {"speaker_label": "SM_0", "audio_source_id": "secondary", "source_is_isolated": True,
           "attribution_confidence": 0.9, "segment_id": "seg-42"}
    p = build_observation_payload_from_segment(seg)
    # MeetingRoom observes, затем SessionManager._signal_flow видит тот же segment
    assert sm.observe_speaker_audio_attribution(p) == 1
    assert sm.observe_speaker_audio_attribution(dict(p)) == 0  # дедуп по segment_id
    assert sm._speaker_audio_attribution.get_stats().observation_count == 1


# --- Stage 9: bridge_segment_source_attribution ---

def test_bridge_attaches_safe_attribution_and_feeds_tracker():
    from app.core.transcription.models import CommittedSegment
    sm = SessionManager(0)
    seg = CommittedSegment(speaker_label="SM_1", segment_id="seg-7")
    ok = sm.bridge_segment_source_attribution(
        seg, audio_source_id="secondary", source_is_isolated=True, attribution_confidence=0.86,
        attribution_source="secondary_shadow_segment", source_kind="secondary_shadow")
    assert ok is True
    assert seg.source_attribution is not None
    assert seg.source_attribution["audio_source_id"] == "secondary"
    # привязанный сегмент → observation через MeetingRoom-payload
    from app.core.context.segment_source_attribution import build_observation_payload_from_segment
    n = sm.observe_speaker_audio_attribution(build_observation_payload_from_segment(seg))
    assert n == 1
    assert _by_label(sm._collect_speaker_audio_metadata())["SM_1"].audio_source_id == "secondary"


def test_bridge_returns_false_for_primary_room_mic():
    from app.core.transcription.models import CommittedSegment
    sm = SessionManager(0)
    seg = CommittedSegment(speaker_label="SM_0", segment_id="seg-8")
    ok = sm.bridge_segment_source_attribution(
        seg, audio_source_id="primary", source_kind="room_mic", source_is_isolated=False,
        attribution_confidence=0.9)
    assert ok is False
    assert seg.source_attribution is None  # ничего не проставлено


# --- Stage 10: reconciliation ---

def _isolated_candidate(**kw):
    base = dict(text="дайте лучше условия", start_ms=1000, end_ms=3000, audio_source_id="secondary",
                source_is_isolated=True, source_kind="multi_channel",
                attribution_source="multi_source_segment", attribution_confidence=0.8,
                candidate_pipeline="multi_channel_live")
    base.update(kw)
    return base


def test_observe_source_candidate_accepts_isolated():
    sm = SessionManager(0)
    assert sm.observe_source_attribution_candidate(_isolated_candidate()) == 1
    assert sm._source_attribution_reconciler.get_stats().candidate_count == 1


def test_observe_source_candidate_rejects_room_mic():
    sm = SessionManager(0)
    assert sm.observe_source_attribution_candidate(
        _isolated_candidate(audio_source_id="primary", source_kind="room_mic",
                            source_is_isolated=False)) == 0


def test_reconcile_attaches_source_attribution_to_committed_segment():
    from app.core.transcription.models import CommittedSegment
    sm = SessionManager(0)
    sm.ai_settings = {"source_reconcile_shadow_mode": False}  # Этап 11: active attach
    sm.observe_source_attribution_candidate(_isolated_candidate())
    seg = CommittedSegment(speaker_label="SM_1", segment_id="s1", text="дайте лучше условия")
    seg.speech_start_ms, seg.speech_end_ms = 1100, 2900
    assert sm.reconcile_source_attribution_for_segment(seg) is True
    assert seg.source_attribution is not None
    assert seg.source_attribution["audio_source_id"] == "secondary"
    assert seg.source_attribution["speaker_label"] == "SM_1"
    assert "side" not in seg.source_attribution


def test_reconcile_does_not_overwrite_manual_bridge():
    from app.core.transcription.models import CommittedSegment
    sm = SessionManager(0)
    sm.ai_settings = {"source_reconcile_shadow_mode": False}  # active
    sm.observe_source_attribution_candidate(_isolated_candidate(audio_source_id="channel_x"))
    seg = CommittedSegment(speaker_label="SM_1", segment_id="s1", text="дайте лучше условия")
    seg.speech_start_ms, seg.speech_end_ms = 1100, 2900
    # manual bridge ставит attribution первым
    sm.bridge_segment_source_attribution(seg, audio_source_id="manual_src", source_is_isolated=True,
                                         attribution_confidence=0.9, source_kind="isolated_source",
                                         attribution_source="manual_runtime_metadata")
    assert seg.source_attribution["audio_source_id"] == "manual_src"
    # reconcile НЕ перезаписывает
    assert sm.reconcile_source_attribution_for_segment(seg) is False
    assert seg.source_attribution["audio_source_id"] == "manual_src"


def test_reconcile_then_committed_observation_feeds_tracker():
    from app.core.transcription.models import CommittedSegment
    from app.core.context.segment_source_attribution import build_observation_payload_from_segment
    sm = SessionManager(0)
    sm.ai_settings = {"source_reconcile_shadow_mode": False}  # active attach
    # conf 0.9 → одиночное isolated наблюдение создаёт stable link (Rule B порог 0.85)
    sm.observe_source_attribution_candidate(_isolated_candidate(attribution_confidence=0.9))
    seg = CommittedSegment(speaker_label="SM_1", segment_id="s1", text="дайте лучше условия")
    seg.speech_start_ms, seg.speech_end_ms = 1100, 2900
    sm.reconcile_source_attribution_for_segment(seg)
    sm.observe_speaker_audio_attribution(build_observation_payload_from_segment(seg))
    assert _by_label(sm._collect_speaker_audio_metadata())["SM_1"].audio_source_id == "secondary"


# --- Stage 11: canary controls ---

def _seg_for_reconcile():
    from app.core.transcription.models import CommittedSegment
    seg = CommittedSegment(speaker_label="SM_1", segment_id="s1", text="дайте лучше условия")
    seg.speech_start_ms, seg.speech_end_ms = 1100, 2900
    return seg


def test_default_shadow_does_not_attach():
    sm = SessionManager(0)  # ai_settings None → global shadow=true
    sm.observe_source_attribution_candidate(_isolated_candidate())
    seg = _seg_for_reconcile()
    assert sm.reconcile_source_attribution_for_segment(seg) is False
    assert seg.source_attribution is None  # shadow → не прикрепили
    assert sm._reconcile_would_attach == 1  # но would_attach посчитан


def test_session_override_shadow_false_attaches():
    sm = SessionManager(0)
    sm.ai_settings = {"source_reconcile_shadow_mode": False}
    sm.observe_source_attribution_candidate(_isolated_candidate())
    seg = _seg_for_reconcile()
    assert sm.reconcile_source_attribution_for_segment(seg) is True
    assert seg.source_attribution is not None


def test_enabled_false_blocks_candidate_and_reconcile():
    sm = SessionManager(0)
    sm.ai_settings = {"source_reconcile_enabled": False}
    assert sm.observe_source_attribution_candidate(_isolated_candidate()) == 0
    seg = _seg_for_reconcile()
    assert sm.reconcile_source_attribution_for_segment(seg) is False
    assert seg.source_attribution is None


def test_bridge_still_explicit_under_shadow():
    from app.core.transcription.models import CommittedSegment
    sm = SessionManager(0)  # global shadow=true
    seg = CommittedSegment(speaker_label="SM_1", segment_id="s1")
    # bridge — явный internal вызов, не подчиняется shadow reconcile
    assert sm.bridge_segment_source_attribution(
        seg, audio_source_id="secondary", source_is_isolated=True, attribution_confidence=0.9,
        source_kind="isolated_source", attribution_source="manual_runtime_metadata") is True
    assert seg.source_attribution is not None


# --- Stage 15: audio capture route metadata (diagnostic only) ---

def test_set_audio_capture_metadata_stores_safe_meta():
    sm = SessionManager(0)
    ok = sm.set_audio_capture_metadata({
        "route": "usb_recorder", "capturePipeline": "stereo_requested_mono_stream",
        "actualChannelCount": 1, "actualSampleRate": 16000})
    assert ok is True
    meta = sm.get_audio_capture_metadata()
    assert meta is not None
    assert meta.route == "usb_recorder"
    assert meta.source_kind == "usb_recorder"
    assert meta.actual_channel_count == 1


def test_set_audio_capture_metadata_hashes_raw_label_id():
    sm = SessionManager(0)
    sm.set_audio_capture_metadata({"route": "speakerphone_usb",
                                   "deviceLabel": "Jabra Speak 510", "deviceId": "raw-id-xyz"})
    meta = sm.get_audio_capture_metadata()
    import json as _json
    blob = _json.dumps(meta.model_dump(), ensure_ascii=False)
    assert "Jabra" not in blob and "raw-id-xyz" not in blob
    assert meta.device_label_hash and meta.device_id_hash


def test_set_audio_capture_metadata_does_not_touch_speaker_audio_or_attribution():
    sm = SessionManager(0)
    sm.set_audio_capture_metadata({"route": "usb_recorder", "deviceLabel": "Zoom H2n"})
    # НЕ создаёт speaker↔audio link и НЕ кормит attribution tracker
    assert sm._collect_speaker_audio_metadata() is None
    assert sm.speaker_audio_source_map == {}
    assert sm.speaker_channel_map == {}
    assert sm._speaker_audio_attribution.get_stats().observation_count == 0


def test_set_audio_capture_metadata_invalid_payload_ignored_safely():
    sm = SessionManager(0)
    # не dict/object → парсер вернёт дефолт unknown, но не упадёт
    assert sm.set_audio_capture_metadata(42) is True
    assert sm.get_audio_capture_metadata().route == "unknown"


def test_set_audio_capture_metadata_does_not_log_raw_label(caplog):
    import logging
    sm = SessionManager(0)
    with caplog.at_level(logging.INFO):
        sm.set_audio_capture_metadata({"route": "usb_recorder", "deviceLabel": "Zoom H2n SECRETLABEL",
                                       "deviceId": "SECRETDEVICEID"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "SECRETLABEL" not in text
    assert "SECRETDEVICEID" not in text
    assert "[AudioCapture]" in text  # агрегированный лог есть


# --- Stage 16: multichannel v2 shadow ingest (diagnostic only) ---

def _v2_frame(seq=1, channels=2):
    import array
    from app.core.context.audio_frame_v2 import build_audio_frame_v2
    h = dict(protocol_version=2, sequence=seq, sample_rate=16000, channels=channels, codec="pcm16",
             layout="interleaved", route="usb_recorder", capture_pipeline="multichannel_shadow_stream")
    return build_audio_frame_v2(h, array.array("h", (1000, -1000) * channels).tobytes())


def test_ingest_v2_shadow_accepted_when_enabled():
    sm = SessionManager(0)
    assert sm.ingest_audio_frame_v2_shadow(_v2_frame()) is True
    st = sm.get_multichannel_shadow_stats()
    assert st.frame_count == 1
    assert st.last_channels == 2
    assert st.enabled is True


def test_ingest_v2_shadow_does_not_touch_speaker_or_source_attribution():
    sm = SessionManager(0)
    sm.ingest_audio_frame_v2_shadow(_v2_frame())
    assert sm._collect_speaker_audio_metadata() is None
    assert sm.speaker_audio_source_map == {} and sm.speaker_channel_map == {}
    assert sm._speaker_audio_attribution.get_stats().observation_count == 0
    assert sm._source_attribution_reconciler.get_stats().candidate_count == 0


def test_ingest_v2_shadow_parse_error_safe():
    sm = SessionManager(0)
    assert sm.ingest_audio_frame_v2_shadow(b"not-a-frame") is False
    assert sm.get_multichannel_shadow_stats().parse_error_count == 1
    assert sm.get_multichannel_shadow_stats().frame_count == 0


def test_ingest_v2_shadow_disabled_config_ignores(monkeypatch):
    from app.config import get_settings
    sm = SessionManager(0)
    s = get_settings()
    monkeypatch.setattr(s, "ai_audio_multichannel_shadow_enabled", False)
    assert sm.ingest_audio_frame_v2_shadow(_v2_frame()) is False
    assert sm.get_multichannel_shadow_stats().frame_count == 0


def test_ingest_v2_shadow_accept_disabled_marks_dropped(monkeypatch):
    from app.config import get_settings
    sm = SessionManager(0)
    s = get_settings()
    monkeypatch.setattr(s, "ai_audio_multichannel_shadow_accept_frames", False)
    assert sm.ingest_audio_frame_v2_shadow(_v2_frame()) is False
    st = sm.get_multichannel_shadow_stats()
    assert st.frame_count == 0 and st.dropped_frame_count == 1


# --- Stage 17: per-channel STT canary (session integration) ---

class _FakeSttAdapter:
    """Provider-адаптер с интерфейсом Этапа 18."""
    provider = "fake"

    async def transcribe_segment(self, segment, config):
        from app.core.audio.per_channel_stt_adapter import PerChannelSttAdapterResult, hash_text
        t = "дайте лучше условия пожалуйста"
        return PerChannelSttAdapterResult(text=t, text_hash=hash_text(t), confidence=0.9,
                                          provider="fake", latency_ms=5)


def _loud_v2(seq, a0=8000, a1=40, frames=1600, created=0):
    import array
    from app.core.context.audio_frame_v2 import build_audio_frame_v2
    h = dict(protocol_version=2, sequence=seq, sample_rate=16000, channels=2, codec="pcm16",
             layout="interleaved", route="usb_recorder", capture_pipeline="multichannel_shadow_stream",
             frame_duration_ms=100, created_at_ms=created)
    return build_audio_frame_v2(h, array.array("h", [a0, a1] * frames).tobytes())


_PCS_OVR = {"audio_per_channel_stt_enabled": True, "audio_per_channel_stt_min_rms": 0.01,
            "audio_per_channel_stt_min_dominance": 0.55, "audio_per_channel_stt_min_segment_ms": 200,
            "audio_per_channel_stt_end_silence_ms": 200, "audio_per_channel_stt_min_text_chars": 4}


async def _feed_loud(sm):
    for i in range(5):
        sm.ingest_audio_frame_v2_shadow(_loud_v2(i, created=1000 + i * 100))
    for i in range(5, 8):
        sm.ingest_audio_frame_v2_shadow(_loud_v2(i, a0=25, a1=25))
    await sm.drain_per_channel_stt_tasks()


async def test_per_channel_stt_disabled_no_candidate():
    sm = SessionManager(0)
    sm._per_channel_stt_adapter = _FakeSttAdapter()
    sm.ai_settings = {}  # disabled (global default)
    await _feed_loud(sm)
    assert sm._per_channel_stt_pipeline is None
    assert sm._source_attribution_reconciler.get_stats().candidate_count == 0


async def test_per_channel_stt_shadow_suppresses_candidate():
    sm = SessionManager(0)
    sm._per_channel_stt_adapter = _FakeSttAdapter()
    sm.ai_settings = dict(_PCS_OVR)  # shadow_mode default true
    await _feed_loud(sm)
    st = sm.get_per_channel_stt_stats()
    assert st.transcribe_success_count >= 1          # STT вызвался
    assert st.candidate_shadow_suppressed_count >= 1
    assert st.candidate_emit_count == 0
    assert sm._source_attribution_reconciler.get_stats().candidate_count == 0  # reconciler не кормлен


async def test_per_channel_stt_active_feeds_reconciler():
    sm = SessionManager(0)
    sm._per_channel_stt_adapter = _FakeSttAdapter()
    sm.ai_settings = dict(_PCS_OVR, audio_per_channel_stt_shadow_mode=False)
    await _feed_loud(sm)
    st = sm.get_per_channel_stt_stats()
    assert st.candidate_emit_count >= 1
    assert sm._source_attribution_reconciler.get_stats().candidate_count >= 1


async def test_per_channel_stt_tasks_drained_no_leak():
    # после drain не остаётся висящих задач (не переживут teardown сессии)
    sm = SessionManager(0)
    sm._per_channel_stt_adapter = _FakeSttAdapter()
    sm.ai_settings = dict(_PCS_OVR, audio_per_channel_stt_shadow_mode=False)
    await _feed_loud(sm)  # включает drain
    assert sm._per_channel_stt_tasks == set()


async def test_per_channel_stt_does_not_infer_side_or_touch_speaker():
    sm = SessionManager(0)
    sm._per_channel_stt_adapter = _FakeSttAdapter()
    sm.ai_settings = dict(_PCS_OVR, audio_per_channel_stt_shadow_mode=False)
    await _feed_loud(sm)
    # не трогает speaker maps / attribution observations / hints
    assert sm._collect_speaker_audio_metadata() is None
    assert sm.speaker_audio_source_map == {} and sm.speaker_channel_map == {}
    assert sm._speaker_audio_attribution.get_stats().observation_count == 0


async def test_per_channel_stt_failure_does_not_break_v2_shadow():
    class _BoomAdapter:
        provider = "fake"

        async def transcribe_segment(self, segment, config):
            raise RuntimeError("stt boom")

    sm = SessionManager(0)
    sm._per_channel_stt_adapter = _BoomAdapter()
    sm.ai_settings = dict(_PCS_OVR, audio_per_channel_stt_shadow_mode=False)
    await _feed_loud(sm)
    # v2 shadow stats всё равно посчитаны; кандидатов нет; поток не упал
    assert sm.get_multichannel_shadow_stats().frame_count == 8
    assert sm._source_attribution_reconciler.get_stats().candidate_count == 0


async def test_per_channel_stt_default_adapter_is_noop():
    # без инъекции адаптера и provider=noop (default) → pipeline строит Noop, кандидатов нет
    sm = SessionManager(0)
    sm.ai_settings = dict(_PCS_OVR, audio_per_channel_stt_shadow_mode=False)  # provider остаётся noop
    await _feed_loud(sm)
    from app.core.audio.per_channel_stt_adapter import NoopPerChannelSttAdapter
    assert isinstance(sm._per_channel_stt_pipeline.adapter, NoopPerChannelSttAdapter)
    assert sm.get_per_channel_stt_stats().adapter_unavailable_count >= 1
    assert sm._source_attribution_reconciler.get_stats().candidate_count == 0


async def test_per_channel_stt_elevenlabs_missing_key_safe():
    # provider=elevenlabs_batch, но ключа нет → api_key_missing, без падения, без кандидатов
    sm = SessionManager(0)
    sm._elevenlabs_key = None
    sm.ai_settings = dict(_PCS_OVR, audio_per_channel_stt_shadow_mode=False,
                          audio_per_channel_stt_provider="elevenlabs_batch")
    await _feed_loud(sm)
    st = sm.get_per_channel_stt_stats()
    assert st.provider == "elevenlabs_batch"
    assert st.last_error_kind in ("api_key_missing", None)
    assert sm._source_attribution_reconciler.get_stats().candidate_count == 0
    # v2 shadow stats не затронуты
    assert sm.get_multichannel_shadow_stats().frame_count == 8


async def test_per_channel_stt_no_raw_text_in_caplog(caplog):
    import logging
    sm = SessionManager(0)
    sm._per_channel_stt_adapter = _FakeSttAdapter()
    sm.ai_settings = dict(_PCS_OVR, audio_per_channel_stt_shadow_mode=False)
    with caplog.at_level(logging.DEBUG):
        await _feed_loud(sm)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "дайте лучше условия" not in text
    assert "channel_0" not in text
