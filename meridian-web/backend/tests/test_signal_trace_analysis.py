"""Этап 3: offline-анализатор логов SIGNAL_ENGINE_TRACE."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.signal_trace_analysis import (
    analyze_signal_traces,
    extract_trace_json_from_line,
    load_trace_events_from_lines,
    percentile,
)


def _event(**kw) -> dict:
    base = dict(
        check_id="x", situation_type="price_pressure", decision_reason="allowed",
        error_kind="none", would_prompt_without_shadow=True, actual_should_prompt=True,
        novelty_key="price_pressure:counterparty:x", score=0.5, latency_ms=100,
    )
    base.update(kw)
    return base


def _line(event: dict) -> str:
    return "2026-06-29 12:00:00 INFO meridian.session SIGNAL_ENGINE_TRACE " + json.dumps(event, ensure_ascii=False)


# --- extract / load ---

def test_extract_parses_valid_line():
    obj = extract_trace_json_from_line(_line(_event(check_id="abc")))
    assert obj is not None
    assert obj["check_id"] == "abc"


def test_extract_ignores_line_without_marker():
    assert extract_trace_json_from_line("2026-06-29 INFO some other log line") is None
    assert extract_trace_json_from_line("") is None


def test_extract_ignores_broken_json():
    assert extract_trace_json_from_line("SIGNAL_ENGINE_TRACE {not valid json,,,") is None


# --- Stage 15: audio_capture summary ---

def _ac(**kw) -> dict:
    return _event(audio_capture_route=kw.get("route", "usb_recorder"),
                  audio_capture_pipeline=kw.get("pipeline", "stereo_requested_mono_stream"),
                  audio_capture_actual_channel_count=kw.get("ch", 1),
                  audio_capture_actual_sample_rate=kw.get("sr", 16000),
                  audio_capture_source_kind=kw.get("sk", "usb_recorder"))


def test_audio_capture_summary_by_route_and_pipeline():
    summ = analyze_signal_traces([_ac() for _ in range(4)] + [_ac(route="laptop_mic", pipeline="mono_stream", sk="unknown")])
    ac = summ["audio_capture"]
    assert ac["events_with_audio_capture"] == 5
    assert ac["by_route"] == {"usb_recorder": 4, "laptop_mic": 1}
    assert ac["by_pipeline"]["stereo_requested_mono_stream"] == 4
    assert ac["actual_channel_count_p50"] == 1.0
    assert ac["actual_sample_rate_p50"] == 16000.0


def test_audio_capture_note_usb_recorder_mono():
    summ = analyze_signal_traces([_ac() for _ in range(5)])  # usb_recorder, pipeline mono (not multichannel)
    assert any("multichannel" in n for n in summ["notes"])


def test_audio_capture_note_laptop_default():
    summ = analyze_signal_traces([_ac(route="laptop_mic", pipeline="mono_stream", sk="unknown") for _ in range(5)])
    assert any("laptop/default" in n for n in summ["notes"])


def test_audio_capture_no_warning_when_absent():
    summ = analyze_signal_traces([_event() for _ in range(5)])
    assert summ["audio_capture"]["events_with_audio_capture"] == 0
    assert not any("audio route" in n or "multichannel" in n for n in summ["notes"])
    # пустой лог тоже без падения
    assert analyze_signal_traces([])["audio_capture"]["events_with_audio_capture"] == 0


# --- Stage 16: audio_multichannel summary ---

def _mc(**kw) -> dict:
    return _ac(route=kw.get("route", "usb_recorder"),
               **{k: v for k, v in kw.items() if k != "route"}) | dict(
        audio_multichannel_frame_count=kw.get("frames", 10),
        audio_multichannel_max_channels_seen=kw.get("maxch", 2),
        audio_multichannel_parse_error_count=kw.get("errors", 0),
        audio_multichannel_sequence_gap_count=kw.get("gaps", 0),
        audio_multichannel_clipping_event_count=kw.get("clip", 0))


def test_audio_multichannel_summary():
    summ = analyze_signal_traces([_mc() for _ in range(4)])
    mc = summ["audio_multichannel"]
    assert mc["events_with_multichannel"] == 4
    assert mc["frame_count_p50"] == 10
    assert mc["max_channels_seen_p50"] == 2
    # пустой лог — без падения
    assert analyze_signal_traces([])["audio_multichannel"]["events_with_multichannel"] == 0


def test_note_usb_route_but_no_v2_frames():
    # usb_recorder route, но multichannel frame_count отсутствует → заметка про opt-in
    summ = analyze_signal_traces([_ac(route="usb_recorder") for _ in range(5)])
    assert any("v2 multichannel shadow frames не приходят" in n for n in summ["notes"])


def test_note_max_channels_2plus():
    summ = analyze_signal_traces([_mc(maxch=2) for _ in range(5)])
    assert any("Stage 17 per-channel STT" in n for n in summ["notes"])


def test_note_parse_errors_and_gaps():
    summ = analyze_signal_traces([_mc(errors=3, gaps=10) for _ in range(5)])
    assert any("parse errors" in n for n in summ["notes"])
    assert any("backpressure" in n for n in summ["notes"])


# --- Stage 17: audio_per_channel_stt summary ---

def _pcs(**kw) -> dict:
    return _mc(maxch=kw.get("maxch", 2)) | dict(
        audio_per_channel_stt_enabled=kw.get("enabled", True),
        audio_per_channel_stt_shadow_mode=kw.get("shadow", True),
        audio_per_channel_stt_segment_finalized_count=kw.get("finalized", 3),
        audio_per_channel_stt_transcribe_success_count=kw.get("success", 3),
        audio_per_channel_stt_candidate_emit_count=kw.get("emit", 0),
        audio_per_channel_stt_candidate_shadow_suppressed_count=kw.get("suppressed", 3),
        audio_per_channel_stt_average_dominance=kw.get("dom", 0.8))


def test_per_channel_stt_summary():
    summ = analyze_signal_traces([_pcs() for _ in range(4)])
    pcs = summ["audio_per_channel_stt"]
    assert pcs["events_enabled"] == 4
    assert pcs["segment_finalized_p50"] == 3
    assert pcs["shadow_suppressed_p50"] == 3
    # empty без падения
    assert analyze_signal_traces([])["audio_per_channel_stt"]["events_enabled"] == 0


def test_note_multichannel_ready_but_stt_disabled():
    # multichannel 2+ канала, но per-channel STT выключен
    summ = analyze_signal_traces([_mc(maxch=2) for _ in range(5)])
    assert any("per-channel STT canary выключен" in n for n in summ["notes"])


def test_note_per_channel_shadow_suppressed():
    summ = analyze_signal_traces([_pcs(suppressed=5, emit=0) for _ in range(5)])
    assert any("снять per-channel shadow" in n for n in summ["notes"])


def test_note_candidates_but_no_reconcile_match():
    # candidates есть, но source_reconcile would_attach=0
    summ = analyze_signal_traces([_pcs(emit=4, source_reconcile_would_attach_count=0) for _ in range(5)])
    assert any("source reconciliation не матчит" in n for n in summ["notes"])


def test_load_trace_events_filters_noise():
    lines = [
        _line(_event(check_id="a")),
        "unrelated log line",
        "SIGNAL_ENGINE_TRACE {broken",
        _line(_event(check_id="b")),
    ]
    events = load_trace_events_from_lines(lines)
    assert [e["check_id"] for e in events] == ["a", "b"]


# --- percentile ---

def test_percentile_basics():
    assert percentile([], 50) is None
    assert percentile([5], 50) == 5.0
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([1, 2, 3, 4], 100) == 4.0


# --- analyze ---

def test_analyze_counts_and_rates():
    events = [
        _event(would_prompt_without_shadow=True, actual_should_prompt=True),
        _event(would_prompt_without_shadow=True, actual_should_prompt=False, decision_reason="shadow_mode"),
        _event(would_prompt_without_shadow=False, actual_should_prompt=False, decision_reason="low_confidence"),
    ]
    s = analyze_signal_traces(events)
    assert s["total"] == 3
    assert s["would_prompt_count"] == 2
    assert s["actual_prompt_count"] == 1
    assert abs(s["would_prompt_rate"] - 2 / 3) < 1e-3  # rate округляется до 4 знаков
    assert abs(s["actual_prompt_rate"] - 1 / 3) < 1e-3


def test_analyze_groupings():
    events = [
        _event(decision_reason="allowed", error_kind="none", situation_type="price_pressure"),
        _event(decision_reason="shadow_mode", error_kind="none", situation_type="price_pressure"),
        _event(decision_reason="low_confidence", error_kind="invalid_json", situation_type="stalling"),
    ]
    s = analyze_signal_traces(events)
    assert s["by_decision_reason"]["allowed"] == 1
    assert s["by_decision_reason"]["shadow_mode"] == 1
    assert s["by_error_kind"]["invalid_json"] == 1
    assert s["by_situation_type"]["price_pressure"] == 2


def test_analyze_top_novelty_keys():
    events = [_event(novelty_key="k1") for _ in range(3)] + [_event(novelty_key="k2")]
    s = analyze_signal_traces(events)
    assert s["top_novelty_keys"][0] == {"key": "k1", "count": 3}


def test_analyze_threshold_candidates_present():
    events = [_event(score=i / 100.0) for i in range(100)]
    s = analyze_signal_traces(events)
    rates = [c["target_rate"] for c in s["threshold_candidates"]]
    assert rates == [0.02, 0.05, 0.10]
    for c in s["threshold_candidates"]:
        assert c["score_cutoff"] is not None


def test_analyze_empty():
    s = analyze_signal_traces([])
    assert s["total"] == 0
    assert s["notes"]


def test_notes_high_error_rate():
    events = [_event() for _ in range(9)] + [_event(error_kind="timeout")]
    s = analyze_signal_traces(events)
    assert any("timeout/exception" in n for n in s["notes"])


def test_notes_high_latency():
    events = [_event(latency_ms=6000) for _ in range(20)]
    s = analyze_signal_traces(events)
    assert any("latency p95" in n for n in s["notes"])


def test_notes_duplicate_novelty():
    # один novelty_key доминирует среди would_prompt событий
    events = [_event(novelty_key="dom") for _ in range(8)] + [
        _event(novelty_key=f"u{i}") for i in range(2)
    ]
    s = analyze_signal_traces(events)
    assert any("дубли" in n for n in s["notes"])


# --- CLI ---

def test_cli_runs_on_tempfile(tmp_path: Path):
    log = tmp_path / "trace.log"
    log.write_text("\n".join(_line(_event(check_id=str(i))) for i in range(3)), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.signal_trace_analysis", str(log)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 0
    summary = json.loads(proc.stdout)
    assert summary["total"] == 3


def test_cli_missing_file_exit_code(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.signal_trace_analysis", str(tmp_path / "nope.log")],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 2


# --- speaker_context summary (Этап 4) ---

def _sp_event(side_counts, avg_conf, sources, **kw) -> dict:
    return _event(
        speaker_context_chars=42, speaker_side_counts=side_counts,
        speaker_average_confidence=avg_conf, speaker_sources=sources, **kw,
    )


def test_speaker_context_summary_computed():
    events = [
        _sp_event({"our_side": 1, "counterparty": 1}, 0.9, {"manual_correction": 2}),
        _sp_event({"unknown": 1}, 0.2, {"transcript_label": 1}),
        _event(),  # без speaker context
    ]
    s = analyze_signal_traces(events)
    sp = s["speaker_context"]
    assert sp["events_with_speaker_context"] == 2
    assert sp["by_source"] == {"manual_correction": 2, "transcript_label": 1}
    assert sp["avg_speaker_confidence_p50"] is not None
    assert sp["unknown_side_event_rate"] is not None


def test_note_high_unknown_side_rate():
    events = [_sp_event({"unknown": 2}, 0.3, {"transcript_label": 2}) for _ in range(8)] + [
        _sp_event({"our_side": 1}, 0.9, {"manual_correction": 1}) for _ in range(2)
    ]
    s = analyze_signal_traces(events)
    assert any("unknown speaker side" in n for n in s["notes"])


def test_note_low_avg_speaker_confidence():
    events = [_sp_event({"our_side": 1}, 0.3, {"legacy_role": 1}) for _ in range(5)]
    s = analyze_signal_traces(events)
    assert any("низкая уверенность speaker graph" in n for n in s["notes"])


# --- Этап 5: hint_source_event_rate / p50 / note ---

def _hint_event(hint_count, count=2, unknown=1, **kw) -> dict:
    return _event(
        speaker_context_chars=42, speaker_side_counts={"our_side": 1, "unknown": unknown},
        speaker_average_confidence=0.8, speaker_sources={"manual_correction": hint_count},
        speaker_count=count, speaker_unknown_side_count=unknown,
        speaker_hint_source_count=hint_count, **kw,
    )


def test_hint_source_event_rate_and_p50():
    events = [_hint_event(1) for _ in range(7)] + [_hint_event(0) for _ in range(3)]
    sp = analyze_signal_traces(events)["speaker_context"]
    assert sp["hint_source_event_rate"] == 0.7
    assert sp["speaker_count_p50"] is not None
    assert sp["unknown_side_count_p50"] is not None
    assert sp["hint_source_count_p50"] is not None


def test_note_low_hint_source_rate():
    # все события имеют speaker_context, но почти нет явных hints → note
    events = [_hint_event(0, unknown=1) for _ in range(9)] + [_hint_event(1) for _ in range(1)]
    s = analyze_signal_traces(events)
    assert any("мало явных speaker hints" in n for n in s["notes"])


# --- Этап 6: audio/channel link summary ---

def _audio_event(audio_linked, channel_linked=0, conf=0.8, unknown=0, sources=None, **kw) -> dict:
    return _event(
        speaker_context_chars=42, speaker_side_counts={"our_side": 1, "unknown": unknown},
        speaker_average_confidence=0.8, speaker_sources={"audio_channel": audio_linked},
        speaker_count=2, speaker_unknown_side_count=unknown, speaker_hint_source_count=audio_linked,
        speaker_audio_linked_count=audio_linked, speaker_channel_linked_count=channel_linked,
        speaker_audio_link_average_confidence=conf,
        speaker_audio_link_sources=(sources or {"audio_source_metadata": audio_linked}),
        **kw,
    )


def test_audio_linked_event_rate_and_by_source():
    events = [_audio_event(1) for _ in range(6)] + [_audio_event(0) for _ in range(4)]
    sp = analyze_signal_traces(events)["speaker_context"]
    assert sp["audio_linked_event_rate"] == 0.6
    assert sp["by_audio_link_source"].get("audio_source_metadata", 0) >= 6
    assert sp["audio_linked_count_p50"] is not None
    assert sp["channel_linked_count_p50"] is not None
    assert sp["audio_link_confidence_p50"] is not None


def test_note_audio_links_but_unknown_high():
    # audio links у >50% событий, но unknown side тоже >50%
    events = [_audio_event(1, unknown=1) for _ in range(8)] + [_audio_event(1, unknown=0) for _ in range(1)]
    s = analyze_signal_traces(events)
    assert any("hints не покрывают sources/channels" in n for n in s["notes"])


def test_note_low_audio_link_confidence():
    events = [_audio_event(1, conf=0.3) for _ in range(5)]
    s = analyze_signal_traces(events)
    assert any("низкая уверенность audio/channel links" in n for n in s["notes"])


# --- Этап 7: live attribution summary ---

def _attr_event(obs_count, link_count, ambiguous=0, conf=0.8, unknown=0, sources=None, **kw) -> dict:
    return _event(
        speaker_context_chars=42, speaker_side_counts={"our_side": 1, "unknown": unknown},
        speaker_unknown_side_count=unknown, speaker_count=2,
        speaker_audio_attribution_observation_count=obs_count,
        speaker_audio_attribution_stable_link_count=link_count,
        speaker_audio_attribution_ambiguous_count=ambiguous,
        speaker_audio_attribution_average_confidence=conf,
        speaker_audio_attribution_sources=(sources or {"diarization_metadata": obs_count}),
        **kw,
    )


def test_attribution_summary_fields_calculated():
    events = [_attr_event(3, 1) for _ in range(6)] + [_attr_event(0, 0) for _ in range(4)]
    sp = analyze_signal_traces(events)["speaker_context"]
    assert sp["attribution_source_event_rate"] == 0.6
    assert sp["attribution_observation_count_p50"] is not None
    assert sp["attribution_stable_link_count_p50"] is not None
    assert sp["by_attribution_source"].get("diarization_metadata", 0) >= 6


def test_note_observations_but_no_stable_links():
    # обсервации есть (p50>0), но stable links 0
    events = [_attr_event(3, 0) for _ in range(5)]
    s = analyze_signal_traces(events)
    assert any("нет stable links" in n for n in s["notes"])


def test_note_ambiguous_attribution():
    events = [_attr_event(3, 0, ambiguous=1) for _ in range(5)]
    s = analyze_signal_traces(events)
    assert any("неоднозначно связана" in n for n in s["notes"])


def test_note_low_attribution_with_high_unknown():
    # мало live attribution (rate<0.2) + unknown>0.5
    events = [_attr_event(0, 0, unknown=1) for _ in range(9)] + [_attr_event(3, 1, unknown=0) for _ in range(1)]
    s = analyze_signal_traces(events)
    assert any("мало live audio attribution" in n for n in s["notes"])


# --- Этап 10: source reconciliation summary ---

def _rc_event(cand, match, ambiguous=0, rejected=0, score=0.8, unknown=0, **kw) -> dict:
    return _event(
        speaker_side_counts={"our_side": 1, "unknown": unknown}, speaker_unknown_side_count=unknown,
        speaker_context_chars=42, speaker_count=2,
        source_reconcile_candidate_count=cand,
        source_reconcile_match_attempt_count=(match + rejected + ambiguous),
        source_reconcile_match_count=match, source_reconcile_ambiguous_count=ambiguous,
        source_reconcile_rejected_count=rejected, source_reconcile_average_match_score=score,
        source_reconcile_candidate_sources={"multi_channel_live": cand},
        source_reconcile_match_reasons={"matched": match, "low_overlap": rejected}, **kw)


def test_source_reconciliation_summary_calculated():
    events = [_rc_event(2, 1) for _ in range(6)] + [_rc_event(1, 0) for _ in range(4)]
    sr = analyze_signal_traces(events)["source_reconciliation"]
    assert sr["candidate_count_p50"] is not None
    assert sr["match_count_p50"] is not None
    assert sr["match_rate"] is not None
    assert sr["by_candidate_source"].get("multi_channel_live", 0) >= 10


def test_note_candidates_but_no_matches():
    events = [_rc_event(3, 0, rejected=1) for _ in range(5)]
    s = analyze_signal_traces(events)
    assert any("source candidates, но нет matches" in n for n in s["notes"])


def test_note_ambiguous_reconcile():
    events = [_rc_event(3, 0, ambiguous=1) for _ in range(5)]
    s = analyze_signal_traces(events)
    assert any("ambiguous source attribution" in n for n in s["notes"])


def test_note_reconcile_works_but_unknown_high():
    events = [_rc_event(2, 1, unknown=1) for _ in range(8)] + [_rc_event(2, 1, unknown=0) for _ in range(1)]
    s = analyze_signal_traces(events)
    assert any("hints не покрывают sources/channels" in n for n in s["notes"])


def test_note_low_reconcile_score():
    events = [_rc_event(2, 1, score=0.5) for _ in range(5)]
    s = analyze_signal_traces(events)
    assert any("низкий score source reconciliation" in n for n in s["notes"])
