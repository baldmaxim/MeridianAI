"""Per-channel STT trace + analyzer (Этап 17)."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.per_channel_stt_policy import PerChannelSttRuntimeConfig
from app.core.context.per_channel_stt_trace import (
    build_per_channel_stt_trace_event,
    log_per_channel_stt_trace,
)
from app.core.context.per_channel_stt_trace_analysis import (
    analyze_per_channel_stt_traces,
    extract_per_channel_stt_json_from_line,
)
from app.core.audio.per_channel_stt import PerChannelSttStats


class _CapLogger:
    def __init__(self):
        self.lines = []

    def info(self, msg, *args):
        self.lines.append(msg % args if args else msg)


def _stats(**kw) -> PerChannelSttStats:
    base = dict(enabled=True, shadow_mode=True, frame_count=20, segment_finalized_count=3,
                transcribe_success_count=3, candidate_emit_count=0,
                candidate_shadow_suppressed_count=3, max_channels_seen=2, active_channel_count=2,
                average_dominance=0.8)
    base.update(kw)
    return PerChannelSttStats(**base)


def _cfg():
    return PerChannelSttRuntimeConfig(
        enabled=True, shadow_mode=True, session_overrides_enabled=True, trace_enabled=True,
        trace_sample_rate=1.0, max_channels=2, min_rms=0.012, min_dominance=0.58, min_segment_ms=700,
        end_silence_ms=700, max_segment_ms=8000, min_text_chars=4, max_segments_per_minute=12,
        max_concurrent_transcribes=2, overrides_applied={"audio_per_channel_stt_enabled": True})


def test_trace_event_serializes_no_raw():
    ev = build_per_channel_stt_trace_event(check_id="chk09zk", stats=_stats(), config=_cfg(),
                                           session_id=7, meeting_id=42)
    log = _CapLogger()
    log_per_channel_stt_trace(log, ev)
    assert len(log.lines) == 1
    line = log.lines[0]
    assert line.startswith("PER_CHANNEL_STT_TRACE ")
    obj = extract_per_channel_stt_json_from_line(line)
    assert obj["enabled"] is True and obj["max_channels_seen"] == 2
    # никакого raw text/audio/source ids/channel labels/speaker labels
    for raw in ("channel_0", "дайте", "SM_", "track_", "secondary", "primary"):
        assert raw not in line


def test_extract_ignores_noise():
    assert extract_per_channel_stt_json_from_line("INFO some other line") is None
    assert extract_per_channel_stt_json_from_line("PER_CHANNEL_STT_TRACE {bad json") is None


def _line(stats):
    ev = build_per_channel_stt_trace_event(check_id="c", stats=stats, config=_cfg())
    return "INFO " + "PER_CHANNEL_STT_TRACE " + json.dumps(ev.model_dump(), ensure_ascii=False)


def test_analysis_note_no_segments():
    summ = analyze_per_channel_stt_traces([extract_per_channel_stt_json_from_line(
        _line(_stats(frame_count=20, segment_finalized_count=0)))])
    assert summ["segment_finalized_count"] == 0
    assert any("0 finalized" in n for n in summ["notes"])


def test_analysis_note_shadow_suppressed():
    summ = analyze_per_channel_stt_traces([extract_per_channel_stt_json_from_line(
        _line(_stats(candidate_shadow_suppressed_count=5, candidate_emit_count=0)))])
    assert summ["candidate_shadow_suppressed_count"] == 5
    assert any("shadow" in n for n in summ["notes"])


def test_analysis_note_low_channels():
    summ = analyze_per_channel_stt_traces([extract_per_channel_stt_json_from_line(
        _line(_stats(max_channels_seen=1)))])
    assert any("2+ канала" in n for n in summ["notes"])


def test_analysis_note_stt_errors():
    summ = analyze_per_channel_stt_traces([extract_per_channel_stt_json_from_line(
        _line(_stats(transcribe_error_count=5, transcribe_success_count=0,
                     last_error_kind="stt_adapter_unavailable")))])
    assert summ["transcribe_error_count"] == 5
    assert summ["by_last_error_kind"].get("stt_adapter_unavailable") == 1
    assert any("STT adapter" in n for n in summ["notes"])


def test_analysis_empty():
    summ = analyze_per_channel_stt_traces([])
    assert summ["total"] == 0
    assert summ["notes"]


def test_analysis_provider_cache_budget_fields():
    summ = analyze_per_channel_stt_traces([extract_per_channel_stt_json_from_line(
        _line(_stats(provider="elevenlabs_batch", transcribe_cache_hit_count=3,
                     transcribe_cache_miss_count=1, transcribe_budget_exhausted_count=2,
                     transcribe_timeout_count=1, transcribe_provider_error_count=1,
                     adapter_unavailable_count=0)))])
    assert summ["by_provider"].get("elevenlabs_batch") == 1
    assert summ["cache_hit_rate"] == 0.75
    assert summ["budget_exhausted_count"] == 2
    assert summ["timeout_count"] == 1
    assert summ["provider_error_count"] == 1


def test_analysis_note_provider_noop():
    summ = analyze_per_channel_stt_traces([extract_per_channel_stt_json_from_line(
        _line(_stats(provider="noop", transcribe_success_count=0)))])
    assert any("real STT adapter not active" in n for n in summ["notes"])


def test_analysis_note_api_key_missing():
    summ = analyze_per_channel_stt_traces([extract_per_channel_stt_json_from_line(
        _line(_stats(provider="elevenlabs_batch", last_error_kind="api_key_missing")))])
    assert any("API key missing" in n for n in summ["notes"])


def test_analysis_note_timeout_and_budget():
    summ = analyze_per_channel_stt_traces([extract_per_channel_stt_json_from_line(
        _line(_stats(transcribe_timeout_count=2, transcribe_budget_exhausted_count=3)))])
    assert any("timeout" in n for n in summ["notes"])
    assert any("budget" in n for n in summ["notes"])


def test_trace_provider_fields_no_raw():
    ev = build_per_channel_stt_trace_event(check_id="c", stats=_stats(provider="elevenlabs_batch"), config=_cfg())
    blob = json.dumps(ev.model_dump(), ensure_ascii=False)
    assert ev.provider == "elevenlabs_batch"
    for raw in ("дайте", "channel_0", "track_", "xi-api-key"):
        assert raw not in blob


def test_trace_cost_budget_fields():
    ev = build_per_channel_stt_trace_event(
        check_id="c", stats=_stats(provider_calls_used=7, provider_audio_seconds_used=84.5), config=_cfg())
    assert ev.provider_calls_used == 7
    assert ev.provider_audio_seconds_used == 84.5


def test_cli(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_line(_stats()) for _ in range(3)), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.per_channel_stt_trace_analysis", str(log)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["total"] == 3


def test_cli_missing_file(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.per_channel_stt_trace_analysis", str(tmp_path / "no.log")],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 2
