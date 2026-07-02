"""Source Attribution Reconciliation v1 (Этап 10).

Безопасно сопоставляет основной committed transcript segment (есть speaker_label, но нет
source/channel) с isolated/per-channel source candidate (есть source/channel, но может не быть
speaker_label). При сильном НЕ-ambiguous совпадении строит source_attribution и прикрепляет к
committed segment → дальше работает цепочка Stage 8/7.

Жёсткие правила безопасности:
- НЕ выводим сторону; source/channel/track — техническая зона записи, не сторона/личность.
- НЕ матчим общий primary/room-mic без isolated/per-channel признака.
- Текст используется ТОЛЬКО для технического совпадения сегментов (не для стороны/подсказок).
- raw text / speaker labels / source ids / channel ids / segment ids НЕ логируются и НЕ в trace.
"""

import hashlib
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, field_validator

from .segment_source_attribution import build_segment_source_attribution_dict
from .speaker_audio_links import is_generic_room_source_token, normalize_audio_token
from .speaker_identity import normalize_speaker_label

SourceKindT = Literal[
    "room_mic", "isolated_source", "multi_channel", "secondary_shadow", "manual", "unknown",
]
_ALLOWED_KINDS = {"room_mic", "isolated_source", "multi_channel", "secondary_shadow", "manual", "unknown"}
AttributionSourceT = Literal[
    "multi_source_segment", "secondary_shadow_segment", "diarization_result",
    "manual_runtime_metadata", "committed_segment", "unknown",
]
_ALLOWED_ATTR_SOURCES = {
    "multi_source_segment", "secondary_shadow_segment", "diarization_result",
    "manual_runtime_metadata", "committed_segment", "unknown",
}
CandidateSourceT = Literal[
    "multi_channel_live", "secondary_shadow", "multi_source_ingest", "manual_runtime_metadata",
    "per_channel_stt", "unknown",
]
_ALLOWED_CAND_SOURCES = {
    "multi_channel_live", "secondary_shadow", "multi_source_ingest", "manual_runtime_metadata",
    "per_channel_stt", "unknown",
}

MatchReasonT = Literal[
    "matched", "no_candidates", "no_speaker_label", "no_text_or_time", "candidate_not_isolated",
    "low_confidence", "low_overlap", "low_text_similarity", "ambiguous", "room_mic_blocked",
    "already_attributed",
]
_REJECT_REASONS = {"candidate_not_isolated", "low_confidence", "low_overlap",
                   "low_text_similarity", "room_mic_blocked"}


def _clamp01(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:
        return 0.0
    return max(0.0, min(1.0, f))


def _text_hash(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def normalize_reconcile_text(text: Optional[str]) -> str:
    """Нормализовать текст для similarity: lower, убрать пунктуацию, схлопнуть пробелы."""
    if not text:
        return ""
    t = re.sub(r"[^\w\s]", " ", str(text).lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def text_similarity(a: Optional[str], b: Optional[str]) -> float:
    """Нормализованная похожесть текстов 0..1 (не требует точной пунктуации)."""
    na, nb = normalize_reconcile_text(a), normalize_reconcile_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def time_overlap_ratio(a_start, a_end, b_start, b_end) -> float:
    """Доля пересечения интервалов относительно меньшего интервала, 0..1."""
    if None in (a_start, a_end, b_start, b_end):
        return 0.0
    da, db = (a_end - a_start), (b_end - b_start)
    if da <= 0 or db <= 0:
        return 0.0
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    return _clamp01(overlap / min(da, db))


def _norm_token_id(v: Any) -> Optional[str]:
    return normalize_audio_token(v)


class SourceAttributionCandidate(BaseModel):
    candidate_id: Optional[str] = None
    text: Optional[str] = None
    text_hash: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    turn_index: Optional[int] = None
    audio_source_id: Optional[str] = None
    channel_label: Optional[str] = None
    device_role: Optional[str] = None
    route: Optional[str] = None
    source_is_isolated: bool = False
    source_kind: SourceKindT = "unknown"
    attribution_source: AttributionSourceT = "unknown"
    attribution_confidence: float = 0.0
    source: CandidateSourceT = "unknown"

    @field_validator("candidate_id", "audio_source_id", "channel_label", "device_role", "route",
                     mode="before")
    @classmethod
    def _norm_tok(cls, v):
        return normalize_audio_token(v)

    @field_validator("attribution_confidence", mode="before")
    @classmethod
    def _clamp_conf(cls, v):
        return _clamp01(v)

    @field_validator("source_kind", mode="before")
    @classmethod
    def _norm_kind(cls, v):
        s = str(v).strip().lower() if v else "unknown"
        return s if s in _ALLOWED_KINDS else "unknown"

    @field_validator("attribution_source", mode="before")
    @classmethod
    def _norm_attr(cls, v):
        s = str(v).strip().lower() if v else "unknown"
        return s if s in _ALLOWED_ATTR_SOURCES else "unknown"

    @field_validator("source", mode="before")
    @classmethod
    def _norm_src(cls, v):
        s = str(v).strip().lower() if v else "unknown"
        return s if s in _ALLOWED_CAND_SOURCES else "unknown"

    def model_post_init(self, __context) -> None:
        if self.text and not self.text_hash:
            self.text_hash = _text_hash(self.text)

    def is_isolated_safe(self) -> bool:
        """Кандидат пригоден для match: есть source/channel, isolated/per-channel, не room-mic.

        Жёстко: при source_is_isolated=False общий room-mic ИЛИ generic-токен (primary/desktop/...)
        блокируются НЕЗАВИСИМО от source_kind (противоречивая metadata → безопасный отказ)."""
        if not self.audio_source_id and not self.channel_label:
            return False
        if not self.source_is_isolated:
            if self.source_kind == "room_mic":
                return False
            if is_generic_room_source_token(self.audio_source_id):
                return False
        return True


class CommittedSegmentFingerprint(BaseModel):
    segment_id: Optional[str] = None
    speaker_label: Optional[str] = None
    text: Optional[str] = None
    text_hash: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    turn_index: Optional[int] = None

    @field_validator("speaker_label", mode="before")
    @classmethod
    def _norm_label(cls, v):
        if v is None:
            return None
        n = normalize_speaker_label(v)
        return None if n == "unknown_speaker" else n

    def model_post_init(self, __context) -> None:
        if self.text and not self.text_hash:
            self.text_hash = _text_hash(self.text)


class SourceAttributionMatch(BaseModel):
    matched: bool = False
    reason: MatchReasonT = "no_candidates"
    candidate_source: Optional[str] = None
    source_kind: Optional[str] = None
    attribution_source: Optional[str] = None
    attribution_confidence: float = 0.0
    match_score: float = 0.0
    time_overlap: float = 0.0
    text_similarity: float = 0.0
    source_is_isolated: bool = False
    attribution_dict: Optional[dict] = None


class SourceAttributionReconcilerStats(BaseModel):
    candidate_count: int = 0
    match_attempt_count: int = 0
    match_count: int = 0
    ambiguous_count: int = 0
    rejected_count: int = 0
    by_candidate_source: dict[str, int] = {}
    by_match_reason: dict[str, int] = {}
    average_match_score: float = 0.0


# --- payload extraction ------------------------------------------------------

_CAND_NESTED = ("source_attribution_candidate", "source_attribution", "audio_attribution",
                "multi_source", "segment_metadata", "diarization_metadata")


def _get_raw(item: Any, name: str):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _get(nested: Any, item: Any, *names: str):
    for n in names:
        if isinstance(nested, dict) and nested.get(n) is not None:
            return nested.get(n)
    for n in names:
        v = _get_raw(item, n)
        if v is not None:
            return v
    return None


def extract_source_candidate_from_payload(payload: Any) -> Optional[SourceAttributionCandidate]:
    """Извлечь SourceAttributionCandidate из structured payload. None если нет source/channel."""
    if payload is None:
        return None
    nested = None
    for key in _CAND_NESTED:
        v = _get_raw(payload, key)
        if isinstance(v, dict):
            nested = v
            break
    source_id = _get(nested, payload, "audio_source_id", "source_id", "source", "input_source", "track_id")
    channel = _get(nested, payload, "channel_label", "channel", "channel_name")
    if not source_id and not channel:
        return None
    return SourceAttributionCandidate(
        candidate_id=_get(nested, payload, "candidate_id", "segment_id", "id"),
        text=_get(nested, payload, "text", "transcript"),
        start_ms=_get(nested, payload, "start_ms", "start", "time_start", "timestamp_ms", "start_server_ms"),
        end_ms=_get(nested, payload, "end_ms", "end", "time_end", "end_server_ms"),
        turn_index=_get(nested, payload, "turn_index", "turn"),
        audio_source_id=source_id,
        channel_label=channel,
        device_role=_get(nested, payload, "device_role"),
        route=_get(nested, payload, "route"),
        source_is_isolated=bool(_get(nested, payload, "source_is_isolated", "isolated",
                                     "isolated_source", "per_channel", "per_source") or False),
        source_kind=_get(nested, payload, "source_kind") or "unknown",
        attribution_source=_get(nested, payload, "attribution_source") or "unknown",
        attribution_confidence=_get(nested, payload, "attribution_confidence", "confidence",
                                    "source_confidence") or 0.0,
        source=_get(nested, payload, "candidate_pipeline", "pipeline") or "unknown",
    )


def extract_committed_fingerprint(segment: Any) -> CommittedSegmentFingerprint:
    """Снять fingerprint committed segment для match (speaker_label + текст/время/turn)."""
    return CommittedSegmentFingerprint(
        segment_id=_get(None, segment, "segment_id", "id"),
        speaker_label=_get(None, segment, "speaker_label", "speaker", "label"),
        text=_get(None, segment, "text", "transcript"),
        start_ms=_get(None, segment, "speech_start_ms", "start_ms", "start", "server_ts_ms"),
        end_ms=_get(None, segment, "speech_end_ms", "end_ms", "end"),
        turn_index=_get(None, segment, "turn_index", "turn"),
    )


# --- reconciler --------------------------------------------------------------

class SourceAttributionReconciler:
    def __init__(
        self,
        max_candidates: int = 500,
        max_age_ms: int = 120_000,
        min_candidate_confidence: float = 0.55,
        min_time_overlap: float = 0.45,
        min_text_similarity: float = 0.78,
        min_match_score: float = 0.62,
        ambiguity_margin: float = 0.08,
    ):
        self.max_candidates = max_candidates
        self.max_age_ms = max_age_ms
        self.min_candidate_confidence = min_candidate_confidence
        self.min_time_overlap = min_time_overlap
        self.min_text_similarity = min_text_similarity
        self.min_match_score = min_match_score
        self.ambiguity_margin = ambiguity_margin
        self._candidates: list[SourceAttributionCandidate] = []
        self._latest_end_ms: Optional[int] = None
        self._attempts = 0
        self._matches = 0
        self._ambiguous = 0
        self._rejected = 0
        self._reason_counts: Counter = Counter()
        self._match_scores: list[float] = []

    def clear(self) -> None:
        self._candidates.clear()
        self._latest_end_ms = None
        self._attempts = self._matches = self._ambiguous = self._rejected = 0
        self._reason_counts.clear()
        self._match_scores.clear()

    def apply_runtime_config(self, config) -> None:
        """Этап 11: применить runtime-пороги/лимиты из SourceReconcileRuntimeConfig (или объекта
        с теми же атрибутами). max_candidates уменьшился → buffer обрезается. Не логирует raw."""
        self.min_candidate_confidence = float(getattr(config, "min_candidate_confidence", self.min_candidate_confidence))
        self.min_time_overlap = float(getattr(config, "min_time_overlap", self.min_time_overlap))
        self.min_text_similarity = float(getattr(config, "min_text_similarity", self.min_text_similarity))
        self.min_match_score = float(getattr(config, "min_match_score", self.min_match_score))
        self.ambiguity_margin = float(getattr(config, "ambiguity_margin", self.ambiguity_margin))
        self.max_candidates = int(getattr(config, "max_candidates", self.max_candidates))
        self.max_age_ms = int(getattr(config, "max_age_ms", self.max_age_ms))
        self._prune()

    # ---- candidates ----

    def _coerce_candidate(self, c: Any) -> Optional[SourceAttributionCandidate]:
        if isinstance(c, SourceAttributionCandidate):
            return c
        return extract_source_candidate_from_payload(c)

    def observe_candidate(self, candidate: Any) -> bool:
        c = self._coerce_candidate(candidate)
        if c is None:
            return False
        if not c.is_isolated_safe():
            return False
        if c.attribution_confidence < self.min_candidate_confidence:
            return False
        self._candidates.append(c)
        if c.end_ms is not None:
            self._latest_end_ms = max(self._latest_end_ms or c.end_ms, c.end_ms)
        self._prune()
        return True

    def observe_candidates(self, candidates: Iterable[Any]) -> int:
        return sum(1 for c in candidates if self.observe_candidate(c))

    def _prune(self) -> None:
        # возрастная очистка (относительно последнего end_ms) + ограничение размера
        if self._latest_end_ms is not None and self.max_age_ms > 0:
            cutoff = self._latest_end_ms - self.max_age_ms
            self._candidates = [c for c in self._candidates
                                if c.end_ms is None or c.end_ms >= cutoff]
        if len(self._candidates) > self.max_candidates:
            self._candidates = self._candidates[-self.max_candidates:]

    def _valid_candidates(self) -> list[SourceAttributionCandidate]:
        return [c for c in self._candidates if c.is_isolated_safe()]

    # ---- matching ----

    @staticmethod
    def _explicit_match(fp: CommittedSegmentFingerprint, c: SourceAttributionCandidate) -> bool:
        if fp.turn_index is not None and c.turn_index is not None and fp.turn_index == c.turn_index:
            return True
        if c.candidate_id and fp.segment_id and c.candidate_id == fp.segment_id:
            return True
        return False

    def _score(self, to: float, ts: float, conf: float) -> float:
        return _clamp01(0.45 * to + 0.4 * ts + 0.15 * conf)

    def _eligible(self, explicit, has_time, has_text, to, ts, c):
        if explicit:
            return True, "explicit"
        if has_time and has_text:
            return (to >= self.min_time_overlap and ts >= self.min_text_similarity), "both"
        if has_text and not has_time:
            return (ts >= 0.9), "text_only"
        if has_time and not has_text:
            return (to >= 0.8 and c.attribution_confidence >= 0.85), "time_only"
        return False, "none"

    def reconcile_segment(self, segment: Any) -> SourceAttributionMatch:
        self._attempts += 1
        fp = extract_committed_fingerprint(segment)

        existing = (segment.get("source_attribution") if isinstance(segment, dict)
                    else getattr(segment, "source_attribution", None))
        if existing:
            return self._result(False, "already_attributed")
        if not fp.speaker_label:
            return self._result(False, "no_speaker_label")
        cands = self._valid_candidates()
        if not cands:
            return self._result(False, "no_candidates")

        scored = []
        for c in cands:
            explicit = self._explicit_match(fp, c)
            to = time_overlap_ratio(fp.start_ms, fp.end_ms, c.start_ms, c.end_ms)
            ts = text_similarity(fp.text, c.text)
            has_time = None not in (fp.start_ms, fp.end_ms, c.start_ms, c.end_ms)
            has_text = bool((fp.text or "").strip()) and bool((c.text or "").strip())
            ok, mode = self._eligible(explicit, has_time, has_text, to, ts, c)
            if not ok:
                continue
            score = max(self._score(to, ts, c.attribution_confidence), 0.9) if explicit \
                else self._score(to, ts, c.attribution_confidence)
            scored.append((c, score, to, ts, explicit, mode))

        if not scored:
            return self._reject_reason(cands, fp)

        scored.sort(key=lambda x: x[1], reverse=True)
        best = scored[0]
        c, score, to, ts, explicit, mode = best

        # uniqueness для text-only / time-only режимов
        if mode in ("text_only", "time_only") and len(scored) > 1:
            return self._result(False, "ambiguous", c, score, to, ts)
        # ambiguity margin (кроме явной корреляции)
        if not explicit and len(scored) > 1 and (score - scored[1][1]) < self.ambiguity_margin:
            return self._result(False, "ambiguous", c, score, to, ts)
        # min_match_score применяется только к режиму time+text (text_only/time_only/explicit
        # уже отгейчены своими строгими порогами; их композитный score ниже по построению)
        if mode == "both" and not explicit and score < self.min_match_score:
            return self._result(False, "low_confidence", c, score, to, ts)

        # confidence: explicit → max; both → min(оба сигнала); text_only/time_only → candidate
        # (его строгий mode-gate уже гарантировал сильный матч; композитный score занижен).
        if explicit:
            conf = max(c.attribution_confidence, score)
        elif mode == "both":
            conf = min(c.attribution_confidence, score)
        else:
            conf = c.attribution_confidence
        attribution = build_segment_source_attribution_dict(
            speaker_label=fp.speaker_label, audio_source_id=c.audio_source_id,
            channel_label=c.channel_label, device_role=c.device_role, route=c.route,
            attribution_confidence=conf, source_is_isolated=c.source_is_isolated,
            attribution_source=c.attribution_source, source_kind=c.source_kind,
            turn_index=fp.turn_index, segment_id=fp.segment_id)
        if attribution is None:
            return self._result(False, "room_mic_blocked", c, score, to, ts)

        self._matches += 1
        self._match_scores.append(score)
        return self._result(True, "matched", c, score, to, ts, attribution)

    def _reject_reason(self, cands, fp) -> SourceAttributionMatch:
        fp_has_text = bool((fp.text or "").strip())
        fp_has_time = fp.start_ms is not None and fp.end_ms is not None
        if not fp_has_text and not fp_has_time:
            return self._result(False, "no_text_or_time")
        best_to = max((time_overlap_ratio(fp.start_ms, fp.end_ms, c.start_ms, c.end_ms) for c in cands),
                      default=0.0)
        best_ts = max((text_similarity(fp.text, c.text) for c in cands), default=0.0)
        has_time = fp_has_time and any(
            c.start_ms is not None and c.end_ms is not None for c in cands)
        has_text = fp_has_text and any((c.text or "").strip() for c in cands)
        if has_time and best_to < self.min_time_overlap:
            reason = "low_overlap"
        elif has_text and best_ts < self.min_text_similarity:
            reason = "low_text_similarity"
        else:
            reason = "low_confidence"
        return self._result(False, reason, None, 0.0, best_to, best_ts)

    def _result(self, matched, reason, c=None, score=0.0, to=0.0, ts=0.0,
                attribution=None) -> SourceAttributionMatch:
        self._reason_counts[reason] += 1
        if reason == "ambiguous":
            self._ambiguous += 1
        elif reason in _REJECT_REASONS:
            self._rejected += 1
        return SourceAttributionMatch(
            matched=matched, reason=reason,
            candidate_source=(c.source if c else None),
            source_kind=(c.source_kind if c else None),
            attribution_source=(c.attribution_source if c else None),
            attribution_confidence=(attribution.get("attribution_confidence", 0.0) if attribution else 0.0),
            match_score=round(score, 4), time_overlap=round(to, 4), text_similarity=round(ts, 4),
            source_is_isolated=(c.source_is_isolated if c else False),
            attribution_dict=attribution,
        )

    def get_stats(self) -> SourceAttributionReconcilerStats:
        avg = round(sum(self._match_scores) / len(self._match_scores), 4) if self._match_scores else 0.0
        return SourceAttributionReconcilerStats(
            candidate_count=len(self._candidates),
            match_attempt_count=self._attempts,
            match_count=self._matches,
            ambiguous_count=self._ambiguous,
            rejected_count=self._rejected,
            by_candidate_source=dict(Counter(c.source for c in self._candidates)),
            by_match_reason=dict(self._reason_counts),
            average_match_score=avg,
        )
