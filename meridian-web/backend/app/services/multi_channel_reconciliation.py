"""Channel-aware reconciliation (Этап 9.7) — чистое сопоставление multi-channel candidate
с committed-репликами основного transcript.

Только EVIDENCE-слой: ничего не применяется автоматически, raw transcript не меняется,
новые transcript-сегменты не создаются. Применение стороны — вручную через существующий
слой segment corrections (Этап 8). Всё in-memory и bounded.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal

ReconciliationEntryKind = Literal["matched", "ambiguous", "channel_only", "primary_only"]
SideAgreement = Literal["suggested", "confirmed", "conflict", "unknown"]

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+", re.UNICODE)
_MAX_NORM_INPUT = 4000          # внутренний bounded-вход для нормализации
_MAX_PAIRS = 6000               # жёсткий потолок числа пар
_TEMPORAL_W = 0.6
_TEXT_W = 0.4


# ============================ views / entry / state ============================

@dataclass(frozen=True)
class PrimaryTranscriptSegmentView:
    segment_key: str
    text: str
    start_server_ms: int
    end_server_ms: int
    original_speaker_label: str | None
    effective_speaker_label: str | None
    current_side: str | None
    has_segment_correction: bool
    correction_side: str | None
    corrected_speaker_label: str | None


@dataclass(frozen=True)
class ChannelTranscriptSegmentView:
    segment_id: str
    session_id: str
    channel_index: int
    channels_count: int
    track_id: str
    source_connection_id: str
    source_kind: str
    generation: int
    channel_label: str
    channel_side: str | None
    text: str
    start_server_ms: int
    end_server_ms: int
    provider_confidence: float | None
    speech_final: bool


@dataclass(frozen=True)
class ReconciliationAlternative:
    channel_segment_id: str
    channel_index: int
    match_score: float
    temporal_score: float
    text_score: float


@dataclass(frozen=True)
class ReconciliationEntry:
    entry_id: str
    kind: ReconciliationEntryKind
    primary_segment_key: str | None
    channel_segment_id: str | None
    primary_text: str | None
    channel_text: str | None
    primary_start_server_ms: int | None
    primary_end_server_ms: int | None
    channel_start_server_ms: int | None
    channel_end_server_ms: int | None
    original_speaker_label: str | None
    effective_speaker_label: str | None
    current_side: str | None
    has_segment_correction: bool
    channel_index: int | None
    track_id: str | None
    source_connection_id: str | None
    source_kind: str | None
    generation: int | None
    channel_label: str | None
    channel_side: str | None
    provider_confidence: float | None
    temporal_score: float
    text_score: float
    match_score: float
    hint_confidence: float
    side_agreement: SideAgreement
    can_apply_side: bool
    requires_conflict_confirmation: bool
    alternatives: tuple = ()
    warnings: tuple = ()


@dataclass(frozen=True)
class MultiChannelReconciliationSummary:
    primary_segments: int
    channel_segments: int
    matched: int
    ambiguous: int
    channel_only: int
    primary_only: int
    suggested: int
    confirmed: int
    conflicts: int
    unknown_side: int
    applicable: int


@dataclass(frozen=True)
class MultiChannelReconciliationState:
    session_id: str
    meeting_id: int
    revision: int
    generated_at: datetime
    summary: MultiChannelReconciliationSummary
    entries: tuple
    truncated: bool
    warnings: tuple = ()


# ============================ pure scoring ============================

def normalize_reconciliation_text(text: str) -> str:
    t = (text or "")[:_MAX_NORM_INPUT].lower().replace("ё", "е")
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def reconciliation_tokens(text: str) -> tuple:
    n = normalize_reconciliation_text(text)
    return tuple(n.split(" ")) if n else ()


def text_similarity_score(left: str, right: str) -> float:
    ln = normalize_reconciliation_text(left)
    rn = normalize_reconciliation_text(right)
    if not ln or not rn:
        return 0.0
    lt, rt = set(ln.split(" ")), set(rn.split(" "))
    union = len(lt | rt)
    jacc = (len(lt & rt) / union) if union else 0.0
    ratio = SequenceMatcher(None, ln, rn).ratio()
    return max(0.0, min(1.0, 0.5 * jacc + 0.5 * ratio))


def _is_int_like(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def temporal_overlap_score(*, left_start_ms: int, left_end_ms: int,
                           right_start_ms: int, right_end_ms: int,
                           max_time_delta_ms: int) -> float:
    for v in (left_start_ms, left_end_ms, right_start_ms, right_end_ms):
        if not _is_int_like(v):
            return 0.0
    if left_end_ms < left_start_ms or right_end_ms < right_start_ms or max_time_delta_ms <= 0:
        return 0.0
    # точное совпадение интервалов (в т.ч. нулевая длительность) — идеальное выравнивание
    if left_start_ms == right_start_ms and left_end_ms == right_end_ms:
        return 1.0
    ldur = max(1, left_end_ms - left_start_ms)
    rdur = max(1, right_end_ms - right_start_ms)
    overlap = min(left_end_ms, right_end_ms) - max(left_start_ms, right_start_ms)
    if overlap > 0:
        base = overlap / max(ldur, rdur)
        lmid = (left_start_ms + left_end_ms) / 2
        rmid = (right_start_ms + right_end_ms) / 2
        mid_close = max(0.0, 1.0 - abs(lmid - rmid) / max_time_delta_ms)
        return max(0.0, min(1.0, 0.7 * base + 0.3 * mid_close))
    gap = max(left_start_ms, right_start_ms) - min(left_end_ms, right_end_ms)
    if gap > max_time_delta_ms:
        return 0.0
    return max(0.0, min(1.0, 0.5 * (1.0 - gap / max_time_delta_ms)))


def reconciliation_pair_score(*, primary: PrimaryTranscriptSegmentView,
                              candidate: ChannelTranscriptSegmentView,
                              max_time_delta_ms: int) -> tuple:
    temporal = temporal_overlap_score(
        left_start_ms=primary.start_server_ms, left_end_ms=primary.end_server_ms,
        right_start_ms=candidate.start_server_ms, right_end_ms=candidate.end_server_ms,
        max_time_delta_ms=max_time_delta_ms)
    text = text_similarity_score(primary.text, candidate.text)
    total = max(0.0, min(1.0, _TEMPORAL_W * temporal + _TEXT_W * text))
    return temporal, text, total


def side_hint_confidence(*, match_score: float, provider_confidence: float | None,
                         channel_silence_ratio: float | None = None,
                         clock_quality: str | None = None) -> float:
    conf = match_score
    if provider_confidence is not None:
        conf = 0.9 * match_score + 0.1 * max(0.0, min(1.0, provider_confidence))
    if clock_quality in (None, "poor"):
        conf *= 0.85
    if channel_silence_ratio is not None and channel_silence_ratio > 0.5:
        conf *= max(0.55, 1.0 - 0.3 * (channel_silence_ratio - 0.5))
    return max(0.0, min(1.0, conf))


# ============================ bounded pair generation ============================

def generate_candidate_pairs(*, primary_segments: list, channel_segments: list,
                             max_time_delta_ms: int, min_pair_score: float) -> list:
    """(pi, ci, total, temporal, text) только для близких по времени пар. Two-pointer, bounded."""
    prim = sorted(range(len(primary_segments)), key=lambda i: primary_segments[i].start_server_ms)
    cand = sorted(range(len(channel_segments)), key=lambda i: channel_segments[i].start_server_ms)
    pairs = []
    j_lo = 0
    for pi in prim:
        p = primary_segments[pi]
        win_lo = p.start_server_ms - max_time_delta_ms
        win_hi = p.end_server_ms + max_time_delta_ms
        while j_lo < len(cand) and channel_segments[cand[j_lo]].end_server_ms < win_lo:
            j_lo += 1
        k = j_lo
        while k < len(cand) and channel_segments[cand[k]].start_server_ms <= win_hi:
            ci = cand[k]
            c = channel_segments[ci]
            # нижняя граница окна на каждый кандидат (cand отсортирован по start, не по end):
            # без этой проверки далёкие-в-прошлом кандидаты попадали бы в скоринг.
            if c.end_server_ms < win_lo:
                k += 1
                continue
            temporal, text, total = reconciliation_pair_score(
                primary=p, candidate=c, max_time_delta_ms=max_time_delta_ms)
            if total >= min_pair_score:
                pairs.append((pi, ci, total, temporal, text))
                if len(pairs) >= _MAX_PAIRS:
                    pairs.sort(key=lambda x: (x[0], x[1]))
                    return pairs
            k += 1
    pairs.sort(key=lambda x: (x[0], x[1]))
    return pairs


# ============================ matching ============================

def _entry_start(e: ReconciliationEntry) -> int:
    return e.primary_start_server_ms if e.primary_start_server_ms is not None \
        else (e.channel_start_server_ms if e.channel_start_server_ms is not None else 0)


def _priority_rank(e: ReconciliationEntry) -> int:
    if e.side_agreement == "conflict":
        return 0
    if e.can_apply_side or e.side_agreement == "suggested":
        return 1
    if e.kind == "ambiguous":
        return 2
    if e.side_agreement == "confirmed":
        return 3
    if e.kind == "channel_only":
        return 4
    return 5  # primary_only / прочее


def reconcile_segments(*, meeting_id: int, session_id: str,
                       primary_segments: list, channel_segments: list,
                       max_time_delta_ms: int, min_pair_score: float, match_score: float,
                       suggest_score: float, ambiguity_delta: float, max_entries: int,
                       channel_silence_ratios: dict | None = None,
                       channel_clock_quality: dict | None = None,
                       revision: int = 1) -> MultiChannelReconciliationState:
    sil = channel_silence_ratios or {}
    clk = channel_clock_quality or {}
    pairs = generate_candidate_pairs(
        primary_segments=primary_segments, channel_segments=channel_segments,
        max_time_delta_ms=max_time_delta_ms, min_pair_score=min_pair_score)

    by_primary: dict[int, list] = {}
    for pr in pairs:
        by_primary.setdefault(pr[0], []).append(pr)
    for pi in by_primary:
        by_primary[pi].sort(key=lambda x: (-x[2], -x[3], -x[4],
                                           channel_segments[x[1]].segment_id))

    # ambiguity — внутреннее свойство набора пар primary (best vs second distinct channel)
    ambiguous_primary: dict[int, list] = {}
    for pi, plist in by_primary.items():
        best = plist[0]
        second = next((x for x in plist[1:] if x[1] != best[1]), None)
        if second is not None and (best[2] - second[2]) < ambiguity_delta and second[2] >= min_pair_score:
            ambiguous_primary[pi] = plist[:3]

    # greedy one-to-one для не-ambiguous
    order = sorted(pairs, key=lambda x: (-x[2], -x[3], -x[4],
                                         primary_segments[x[0]].segment_key,
                                         channel_segments[x[1]].segment_id))
    matched: dict[int, tuple] = {}     # pi -> (ci, total, temporal, text)
    used_channel: set = set()
    for (pi, ci, total, temporal, text) in order:
        if pi in matched or pi in ambiguous_primary or ci in used_channel:
            continue
        if total < match_score:
            continue
        matched[pi] = (ci, total, temporal, text)
        used_channel.add(ci)

    entries: list[ReconciliationEntry] = []
    accounted_channels: set = set(used_channel)

    # matched entries
    for pi, (ci, total, temporal, text) in matched.items():
        p = primary_segments[pi]
        c = channel_segments[ci]
        hint = side_hint_confidence(
            match_score=total, provider_confidence=c.provider_confidence,
            channel_silence_ratio=sil.get(c.channel_index), clock_quality=clk.get(c.channel_index))
        agreement, can_apply, needs_conf, warns = _agreement(p, c, total, hint, suggest_score)
        entries.append(_matched_entry(p, c, total, temporal, text, hint, agreement,
                                      can_apply, needs_conf, warns))

    # ambiguous entries
    for pi, top in ambiguous_primary.items():
        p = primary_segments[pi]
        alts = tuple(ReconciliationAlternative(
            channel_segment_id=channel_segments[x[1]].segment_id,
            channel_index=channel_segments[x[1]].channel_index,
            match_score=round(x[2], 4), temporal_score=round(x[3], 4), text_score=round(x[4], 4),
        ) for x in top)
        for x in top:
            accounted_channels.add(x[1])
        entries.append(ReconciliationEntry(
            entry_id=f"reconcile:primary:{p.segment_key}", kind="ambiguous",
            primary_segment_key=p.segment_key, channel_segment_id=None,
            primary_text=p.text, channel_text=None,
            primary_start_server_ms=p.start_server_ms, primary_end_server_ms=p.end_server_ms,
            channel_start_server_ms=None, channel_end_server_ms=None,
            original_speaker_label=p.original_speaker_label,
            effective_speaker_label=p.effective_speaker_label, current_side=p.current_side,
            has_segment_correction=p.has_segment_correction,
            channel_index=None, track_id=None, source_connection_id=None, source_kind=None,
            generation=None, channel_label=None, channel_side=None, provider_confidence=None,
            temporal_score=round(top[0][3], 4), text_score=round(top[0][4], 4),
            match_score=round(top[0][2], 4), hint_confidence=0.0,
            side_agreement="unknown", can_apply_side=False,
            requires_conflict_confirmation=p.has_segment_correction,
            alternatives=alts, warnings=("Неоднозначное соответствие — выберите канал вручную",),
        ))

    # channel_only
    for ci, c in enumerate(channel_segments):
        if ci in accounted_channels:
            continue
        entries.append(ReconciliationEntry(
            entry_id=f"reconcile:channel:{c.segment_id}", kind="channel_only",
            primary_segment_key=None, channel_segment_id=c.segment_id,
            primary_text=None, channel_text=c.text,
            primary_start_server_ms=None, primary_end_server_ms=None,
            channel_start_server_ms=c.start_server_ms, channel_end_server_ms=c.end_server_ms,
            original_speaker_label=None, effective_speaker_label=None, current_side=None,
            has_segment_correction=False,
            channel_index=c.channel_index, track_id=c.track_id,
            source_connection_id=c.source_connection_id, source_kind=c.source_kind,
            generation=c.generation, channel_label=c.channel_label, channel_side=c.channel_side,
            provider_confidence=c.provider_confidence,
            temporal_score=0.0, text_score=0.0, match_score=0.0, hint_confidence=0.0,
            side_agreement="unknown", can_apply_side=False, requires_conflict_confirmation=False,
            warnings=("Эта реплика не найдена в основном transcript",),
        ))

    # primary_only
    for pi, p in enumerate(primary_segments):
        if pi in matched or pi in ambiguous_primary:
            continue
        entries.append(ReconciliationEntry(
            entry_id=f"reconcile:primary:{p.segment_key}", kind="primary_only",
            primary_segment_key=p.segment_key, channel_segment_id=None,
            primary_text=p.text, channel_text=None,
            primary_start_server_ms=p.start_server_ms, primary_end_server_ms=p.end_server_ms,
            channel_start_server_ms=None, channel_end_server_ms=None,
            original_speaker_label=p.original_speaker_label,
            effective_speaker_label=p.effective_speaker_label, current_side=p.current_side,
            has_segment_correction=p.has_segment_correction,
            channel_index=None, track_id=None, source_connection_id=None, source_kind=None,
            generation=None, channel_label=None, channel_side=None, provider_confidence=None,
            temporal_score=0.0, text_score=0.0, match_score=0.0, hint_confidence=0.0,
            side_agreement="unknown", can_apply_side=False, requires_conflict_confirmation=False,
            warnings=("Для реплики не найден уверенный multi-channel match",),
        ))

    summary = _summarize(primary_segments, channel_segments, entries)

    # приоритетная сортировка + обрезка до max_entries
    entries.sort(key=lambda e: (_priority_rank(e), _entry_start(e), e.entry_id))
    truncated = len(entries) > max_entries
    if truncated:
        entries = entries[:max_entries]

    return MultiChannelReconciliationState(
        session_id=session_id, meeting_id=meeting_id, revision=revision,
        generated_at=datetime.utcnow(), summary=summary, entries=tuple(entries),
        truncated=truncated, warnings=(),
    )


def _agreement(p: PrimaryTranscriptSegmentView, c: ChannelTranscriptSegmentView,
               total: float, hint: float, suggest_score: float):
    warns = []
    side = c.channel_side
    if side not in ("self", "opponent"):
        return "unknown", False, False, ("Сторона канала не указана",)
    if p.current_side is None:
        agreement = "suggested"
    elif p.current_side == side:
        agreement = "confirmed"
    else:
        agreement = "conflict"
    can_apply = (hint >= suggest_score and p.segment_key is not None and side in ("self", "opponent"))
    needs_conf = (agreement == "conflict") or p.has_segment_correction
    if agreement == "confirmed":
        can_apply = False  # уже подтверждено — применять нечего
    return agreement, can_apply, needs_conf, tuple(warns)


def _matched_entry(p, c, total, temporal, text, hint, agreement, can_apply, needs_conf, warns):
    return ReconciliationEntry(
        entry_id=f"reconcile:{p.segment_key}:{c.segment_id}", kind="matched",
        primary_segment_key=p.segment_key, channel_segment_id=c.segment_id,
        primary_text=p.text, channel_text=c.text,
        primary_start_server_ms=p.start_server_ms, primary_end_server_ms=p.end_server_ms,
        channel_start_server_ms=c.start_server_ms, channel_end_server_ms=c.end_server_ms,
        original_speaker_label=p.original_speaker_label,
        effective_speaker_label=p.effective_speaker_label, current_side=p.current_side,
        has_segment_correction=p.has_segment_correction,
        channel_index=c.channel_index, track_id=c.track_id,
        source_connection_id=c.source_connection_id, source_kind=c.source_kind,
        generation=c.generation, channel_label=c.channel_label, channel_side=c.channel_side,
        provider_confidence=c.provider_confidence,
        temporal_score=round(temporal, 4), text_score=round(text, 4), match_score=round(total, 4),
        hint_confidence=round(hint, 4), side_agreement=agreement, can_apply_side=can_apply,
        requires_conflict_confirmation=needs_conf, warnings=warns,
    )


def _summarize(primary, channel, entries) -> MultiChannelReconciliationSummary:
    kinds = {"matched": 0, "ambiguous": 0, "channel_only": 0, "primary_only": 0}
    agree = {"suggested": 0, "confirmed": 0, "conflict": 0, "unknown": 0}
    applicable = 0
    for e in entries:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
        agree[e.side_agreement] = agree.get(e.side_agreement, 0) + 1
        if e.can_apply_side:
            applicable += 1
    return MultiChannelReconciliationSummary(
        primary_segments=len(primary), channel_segments=len(channel),
        matched=kinds["matched"], ambiguous=kinds["ambiguous"],
        channel_only=kinds["channel_only"], primary_only=kinds["primary_only"],
        suggested=agree["suggested"], confirmed=agree["confirmed"],
        conflicts=agree["conflict"], unknown_side=agree["unknown"], applicable=applicable,
    )


# ============================ WS payload (bounded text) ============================

def _trunc(text: str | None, max_chars: int) -> str | None:
    if text is None:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def entry_to_dict(e: ReconciliationEntry, *, max_text_chars: int) -> dict:
    return {
        "entry_id": e.entry_id, "kind": e.kind,
        "primary_segment_key": e.primary_segment_key, "channel_segment_id": e.channel_segment_id,
        "primary_text": _trunc(e.primary_text, max_text_chars),
        "channel_text": _trunc(e.channel_text, max_text_chars),
        "primary_start_server_ms": e.primary_start_server_ms,
        "primary_end_server_ms": e.primary_end_server_ms,
        "channel_start_server_ms": e.channel_start_server_ms,
        "channel_end_server_ms": e.channel_end_server_ms,
        "original_speaker_label": e.original_speaker_label,
        "effective_speaker_label": e.effective_speaker_label,
        "current_side": e.current_side, "has_segment_correction": e.has_segment_correction,
        "channel_index": e.channel_index, "track_id": e.track_id,
        "source_connection_id": e.source_connection_id, "source_kind": e.source_kind,
        "generation": e.generation, "channel_label": e.channel_label, "channel_side": e.channel_side,
        "provider_confidence": e.provider_confidence,
        "temporal_score": e.temporal_score, "text_score": e.text_score,
        "match_score": e.match_score, "hint_confidence": e.hint_confidence,
        "side_agreement": e.side_agreement, "can_apply_side": e.can_apply_side,
        "requires_conflict_confirmation": e.requires_conflict_confirmation,
        "alternatives": [{
            "channel_segment_id": a.channel_segment_id, "channel_index": a.channel_index,
            "match_score": a.match_score, "temporal_score": a.temporal_score,
            "text_score": a.text_score,
        } for a in e.alternatives],
        "warnings": list(e.warnings),
    }


def state_to_dict(state: MultiChannelReconciliationState, *, max_text_chars: int) -> dict:
    s = state.summary
    return {
        "session_id": state.session_id, "meeting_id": state.meeting_id,
        "revision": state.revision, "generated_at": state.generated_at.isoformat(),
        "truncated": state.truncated,
        "summary": {
            "primary_segments": s.primary_segments, "channel_segments": s.channel_segments,
            "matched": s.matched, "ambiguous": s.ambiguous, "channel_only": s.channel_only,
            "primary_only": s.primary_only, "suggested": s.suggested, "confirmed": s.confirmed,
            "conflicts": s.conflicts, "unknown_side": s.unknown_side, "applicable": s.applicable,
        },
        "entries": [entry_to_dict(e, max_text_chars=max_text_chars) for e in state.entries],
        "warnings": list(state.warnings),
    }
