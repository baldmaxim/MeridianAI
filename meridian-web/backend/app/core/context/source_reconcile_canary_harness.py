"""Canary readiness harness (Этап 12) — backend-only, in-memory, без БД/LLM/network/frontend.

Прогоняет синтетический сценарий через всю цепочку:
  source candidate → SourceAttributionReconciler → source_attribution → SpeakerAudioAttributionTracker
  → SpeakerAudioLinkMap → speaker_identity_hints → Speaker Identity Graph → speaker_context.

Результат — только безопасные агрегаты + leak_check. Никакого raw text / speaker labels / source ids /
segment ids в stdout/result JSON. Synthetic text используется только in-memory для similarity.
shadow (active=false) считает would_attach, но НЕ прикрепляет source_attribution. Сторона приходит
только из speaker_identity_hints поверх stable link — никакого вывода стороны из source/channel.
"""

import argparse
import hashlib
import json
import sys
from typing import Any, Optional

from .segment_source_attribution import (
    attach_source_attribution_to_committed_segment,
    build_observation_payload_from_segment,
    public_committed_segment_payload,
)
from .source_attribution_policy import (
    SourceReconcileRuntimeConfig,
    evaluate_source_reconcile_decision,
)
from .source_attribution_reconciler import SourceAttributionReconciler
from .speaker_audio_attribution import SpeakerAudioAttributionTracker
from .speaker_identity import build_speaker_context_text


def _hash(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _config_from_case(case: dict, active: bool) -> SourceReconcileRuntimeConfig:
    sr = case.get("source_reconcile") or {}
    return SourceReconcileRuntimeConfig(
        enabled=bool(sr.get("enabled", True)),
        shadow_mode=(not active),
        session_overrides_enabled=True,
        min_candidate_confidence=float(sr.get("min_candidate_confidence", 0.55)),
        min_time_overlap=float(sr.get("min_time_overlap", 0.45)),
        min_text_similarity=float(sr.get("min_text_similarity", 0.78)),
        min_match_score=float(sr.get("min_match_score", 0.62)),
        ambiguity_margin=float(sr.get("ambiguity_margin", 0.08)),
        max_candidates=int(sr.get("max_candidates", 500)),
        max_age_ms=int(sr.get("max_age_ms", 120000)),
    )


def _committed_for_public(seg: dict):
    """CommittedSegment-объект для проверки public payload (то же поведение, что в проде)."""
    from ..transcription.models import CommittedSegment
    cs = CommittedSegment(
        segment_id=str(seg.get("segment_id") or "seg"),
        speaker_label=seg.get("speaker_label"),
        text=str(seg.get("text") or ""),
    )
    if seg.get("source_attribution"):
        cs.source_attribution = seg["source_attribution"]
    return cs


def _build_speaker_map(observation_payload: Optional[dict], identity_hints: Any):
    """observation → tracker → link map → SpeakerIdentityService.build_runtime_map(hints)."""
    from ...services.speaker_identity_service import SpeakerIdentityService
    tracker = SpeakerAudioAttributionTracker()
    if observation_payload:
        tracker.observe(observation_payload)
    link_map = tracker.build_link_map()
    speaker_map = SpeakerIdentityService().build_runtime_map(
        manual_overrides=None, recent_dialog="", identity_hints=identity_hints,
        audio_link_map=link_map)
    return tracker, speaker_map


def run_source_reconcile_canary_case(case: dict, *, active: bool = False) -> dict:
    """Прогнать один синтетический case через цепочку. Result — только безопасные агрегаты."""
    if not isinstance(case, dict) or not isinstance(case.get("committed_segment"), dict):
        raise ValueError("invalid case: требуется dict с committed_segment")
    name = str(case.get("name") or "unnamed")
    seg = dict(case["committed_segment"])  # рабочая копия (на неё кладём source_attribution)
    candidates = case.get("source_candidates") or []
    hints = case.get("speaker_identity_hints")
    config = _config_from_case(case, active)

    reconciler = SourceAttributionReconciler()
    reconciler.apply_runtime_config(config)
    if config.enabled:
        reconciler.observe_candidates(candidates)
        match = reconciler.reconcile_segment(seg)
    else:
        match = reconciler.reconcile_segment(seg)  # без кандидатов → no_candidates
    decision = evaluate_source_reconcile_decision(match, config)

    notes: list[str] = []
    observation_payload = None
    speaker_map = None
    obs_count = 0
    link_count = 0

    if decision.actual_attach and match.attribution_dict:
        attach_source_attribution_to_committed_segment(seg, match.attribution_dict)
        observation_payload = build_observation_payload_from_segment(seg)
        tracker, speaker_map = _build_speaker_map(observation_payload, hints)
        stats = tracker.get_stats()
        obs_count = stats.observation_count
        link_count = stats.stable_link_count
        if not speaker_map.speakers or all(s.side == "unknown" for s in speaker_map.speakers.values()):
            notes.append("attach есть, но сторона unknown — speaker_identity_hints не покрывают source")
    elif decision.would_attach_without_shadow:
        notes.append("shadow: would_attach=true, source_attribution НЕ прикреплён (active=false)")
    else:
        notes.append(f"no attach: decision={decision.reason} match={match.reason}")

    speaker_context = build_speaker_context_text(speaker_map) if (speaker_map and speaker_map.speakers) else ""
    side_counts = dict(speaker_map.side_counts) if speaker_map else {}
    speaker_sources = dict(speaker_map.source_summary) if speaker_map else {}
    avg_conf = speaker_map.average_confidence if (speaker_map and speaker_map.speakers) else None

    # public payload: source_attribution не должен утечь наружу
    public_seg = _committed_for_public(seg)
    public_blob = json.dumps(public_committed_segment_payload(public_seg), ensure_ascii=False)
    wire_blob = json.dumps(public_seg.to_wire_full(), ensure_ascii=False)
    public_has_sa = ("source_attribution" in public_blob) or ("source_attribution" in wire_blob)

    result = {
        "case_name": name,
        "active": active,
        "matched": bool(match.matched),
        "would_attach_without_shadow": bool(decision.would_attach_without_shadow),
        "actual_attach": bool(decision.actual_attach),
        "decision_reason": decision.reason,
        "match_reason": match.reason,
        "match_score": round(match.match_score, 4),
        "time_overlap": round(match.time_overlap, 4),
        "text_similarity": round(match.text_similarity, 4),
        "attribution_confidence": round(match.attribution_confidence, 4),
        "source_candidate_count": reconciler.get_stats().candidate_count,
        "speaker_audio_observation_count": obs_count,
        "speaker_audio_stable_link_count": link_count,
        "speaker_side_counts": side_counts,
        "speaker_sources": speaker_sources,
        "speaker_average_confidence": avg_conf,
        "speaker_context_chars": len(speaker_context),
        "speaker_context_hash": _hash(speaker_context) if speaker_context else None,
        "public_payload_contains_source_attribution": public_has_sa,
        "notes": notes,
    }

    # leak_check: сериализуем result (без leak_check) и ищем raw values, сами values НЕ выводим
    blob = json.dumps(result, ensure_ascii=False)
    raw_texts = [seg.get("text")] + [c.get("text") for c in candidates if isinstance(c, dict)]
    raw_labels = [seg.get("speaker_label")]
    raw_sources = []
    for c in candidates:
        if isinstance(c, dict):
            raw_sources += [c.get("audio_source_id"), c.get("channel_label")]
    for grp in (hints or {}).values() if isinstance(hints, dict) else []:
        if isinstance(grp, dict):
            raw_sources += list(grp.keys())
    raw_seg_ids = [seg.get("segment_id")] + [c.get("candidate_id") for c in candidates if isinstance(c, dict)]

    def _present(values):
        return any(v and str(v) in blob for v in values)

    result["leak_check"] = {
        "contains_raw_text": _present(raw_texts),
        "contains_raw_speaker_label": _present(raw_labels),
        "contains_raw_source_id": _present(raw_sources),
        "contains_raw_segment_id": _present(raw_seg_ids),
    }
    return result


# --- встроенные сценарии -----------------------------------------------------

_SAFE_MATCH = {
    "name": "safe_match",
    "committed_segment": {"segment_id": "seg-1", "speaker_label": "SM_1",
                          "text": "synthetic negotiation utterance one",
                          "speech_start_ms": 1000, "speech_end_ms": 3000, "turn_index": 1},
    "source_candidates": [{
        "candidate_id": "cand-1", "text": "synthetic negotiation utterance one",
        "start_ms": 1000, "end_ms": 3000, "audio_source_id": "track_2", "channel_label": "right",
        "source_is_isolated": True, "source_kind": "multi_channel",
        "attribution_source": "multi_source_segment", "attribution_confidence": 0.9,
        "source": "multi_channel_live"}],
    "speaker_identity_hints": {"audio_sources": {"track_2": {"side": "counterparty",
                              "confidence": 0.8, "source": "audio_channel"}}},
}


def _builtin() -> dict:
    safe = json.loads(json.dumps(_SAFE_MATCH))  # deep copy
    shadow = json.loads(json.dumps(_SAFE_MATCH)); shadow["name"] = "shadow_match"
    unsafe = json.loads(json.dumps(_SAFE_MATCH)); unsafe["name"] = "unsafe_primary_blocked"
    unsafe["source_candidates"][0].update(audio_source_id="primary", channel_label=None,
                                          source_kind="room_mic", source_is_isolated=False)
    ambiguous = json.loads(json.dumps(_SAFE_MATCH)); ambiguous["name"] = "ambiguous_blocked"
    second = json.loads(json.dumps(_SAFE_MATCH["source_candidates"][0]))
    second.update(candidate_id="cand-2", audio_source_id="track_3", channel_label="left")
    ambiguous["source_candidates"].append(second)
    no_hint = json.loads(json.dumps(_SAFE_MATCH)); no_hint["name"] = "no_hint_unknown"
    no_hint["speaker_identity_hints"] = {"audio_sources": {"track_9": {"side": "counterparty",
                                         "confidence": 0.8}}}  # не покрывает track_2
    low_sim = json.loads(json.dumps(_SAFE_MATCH)); low_sim["name"] = "low_similarity_rejected"
    low_sim["source_candidates"][0]["text"] = "completely different unrelated weather chat"
    time_only = json.loads(json.dumps(_SAFE_MATCH)); time_only["name"] = "time_only_strict"
    time_only["committed_segment"]["text"] = None
    time_only["source_candidates"][0]["text"] = None
    time_only["source_candidates"][0]["attribution_confidence"] = 0.9  # >=0.85 для time_only
    return {c["name"]: c for c in (safe, shadow, unsafe, ambiguous, no_hint, low_sim, time_only)}


def get_builtin_canary_case(name: str) -> dict:
    cases = _builtin()
    if name not in cases:
        raise ValueError(f"unknown scenario: {name}")
    return cases[name]


def run_builtin_canary_cases(*, active: bool = False) -> list[dict]:
    return [run_source_reconcile_canary_case(c, active=active) for c in _builtin().values()]


def _main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(prog="source_reconcile_canary_harness", add_help=True)
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--active", action="store_true")
    parser.add_argument("--case-file", default=None)
    args = parser.parse_args(argv[1:])

    try:
        if args.case_file:
            try:
                with open(args.case_file, "r", encoding="utf-8") as f:
                    case = json.load(f)
            except FileNotFoundError:
                print(f"Файл не найден: {args.case_file}", file=sys.stderr)
                return 2
            out = run_source_reconcile_canary_case(case, active=args.active)
        elif args.scenario in (None, "all"):
            out = run_builtin_canary_cases(active=args.active)
        else:
            out = run_source_reconcile_canary_case(get_builtin_canary_case(args.scenario),
                                                   active=args.active)
    except ValueError as e:
        # безопасная ошибка — без дампа raw text/case
        print(f"invalid case/scenario: {type(e).__name__}", file=sys.stderr)
        return 3
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
