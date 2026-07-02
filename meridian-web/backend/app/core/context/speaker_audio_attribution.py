"""Live speaker→audio attribution tracker (Этап 7).

Накапливает structured observations (speaker_label ↔ audio_source_id/channel_label из
сегментов/диаризации/multi-source) и создаёт SpeakerAudioLink ТОЛЬКО когда attribution
устойчива (dominance по нескольким наблюдениям ИЛИ одно isolated high-confidence).

Никакого парсинга transcript text, никакого вывода стороны из source/channel/device токенов.
Сторона появляется отдельно — через speaker_identity_hints + этот link. В stats — только
счётчики/агрегаты, без raw labels/source ids.
"""

from collections import Counter
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, field_validator

from .speaker_audio_links import (
    SpeakerAudioLink,
    SpeakerAudioLinkMap,
    build_speaker_audio_link_map,
    is_generic_room_source_token,
    make_speaker_audio_link,
    normalize_audio_token,
)
from .speaker_identity import make_stable_speaker_id, normalize_speaker_label

SpeakerAudioObservationSource = Literal[
    "segment_metadata",
    "diarization_metadata",
    "multi_source_ingest",
    "secondary_shadow",
    "meeting_room_metadata",
    "manual_runtime_metadata",
    "unknown",
]
_ALLOWED_OBS_SOURCES = {
    "segment_metadata", "diarization_metadata", "multi_source_ingest", "secondary_shadow",
    "meeting_room_metadata", "manual_runtime_metadata", "unknown",
}

# Observation source → SpeakerAudioLink.source (остаёмся в его Literal, не расширяем)
_OBS_TO_LINK_SOURCE = {
    "multi_source_ingest": "meeting_room_metadata",
    "secondary_shadow": "meeting_room_metadata",
    "meeting_room_metadata": "meeting_room_metadata",
    "diarization_metadata": "diarization_metadata",
    "segment_metadata": "diarization_metadata",
    "manual_runtime_metadata": "audio_source_metadata",
    "unknown": "meeting_room_metadata",
}


def _clamp01(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:
        return 0.0
    return max(0.0, min(1.0, f))


def _norm_obs_source(value: Any) -> SpeakerAudioObservationSource:
    if not value:
        return "unknown"
    s = str(value).strip().lower()
    return s if s in _ALLOWED_OBS_SOURCES else "unknown"  # type: ignore[return-value]


class SpeakerAudioObservation(BaseModel):
    raw_speaker_label: str = "unknown_speaker"
    stable_id: str = ""
    audio_source_id: Optional[str] = None
    channel_label: Optional[str] = None
    device_role: Optional[str] = None
    route: Optional[str] = None
    attribution_confidence: float = 0.0
    source: SpeakerAudioObservationSource = "unknown"
    source_is_isolated: bool = False
    turn_index: Optional[int] = None
    dedupe_key: Optional[str] = None  # стабильный id наблюдения (segment_id/turn_id/...) для dedupe

    @field_validator("raw_speaker_label", mode="before")
    @classmethod
    def _norm_label(cls, v):
        return normalize_speaker_label(v)

    @field_validator("audio_source_id", "channel_label", "device_role", "route", mode="before")
    @classmethod
    def _norm_token(cls, v):
        return normalize_audio_token(v)

    @field_validator("attribution_confidence", mode="before")
    @classmethod
    def _clamp_conf(cls, v):
        return _clamp01(v)

    def model_post_init(self, __context) -> None:
        if not self.stable_id:
            self.stable_id = make_stable_speaker_id(self.raw_speaker_label)


class SpeakerAudioAttributionStats(BaseModel):
    observation_count: int = 0
    stable_link_count: int = 0
    speaker_count_observed: int = 0
    ambiguous_speaker_count: int = 0
    average_link_confidence: float = 0.0
    by_observation_source: dict[str, int] = {}
    by_link_source: dict[str, int] = {}
    dedupe_seen_count: int = 0


# --- извлечение observations из structured payload ---------------------------

_TEXT_KEYS = {"text", "transcript", "recent_dialog", "current_text", "full_transcript", "content"}
_OBS_CONTAINER_KEYS = (
    "speaker_audio_links", "audio_source_metadata", "channel_metadata",
    "diarization_metadata", "multi_source", "segment_metadata",
)


def _get(item: Any, *names: str):
    for n in names:
        v = item.get(n) if isinstance(item, dict) else getattr(item, n, None)
        if v is not None:
            return v
    return None


def _obs_from_item(item: Any) -> Optional[SpeakerAudioObservation]:
    if item is None:
        return None
    label = _get(item, "speaker_label", "speaker", "label", "raw_speaker_label")
    if not label:
        return None
    source_id = _get(item, "audio_source_id", "source_id", "source", "input_source", "track_id")
    channel = _get(item, "channel_label", "channel", "channel_name")
    if not source_id and not channel:
        return None
    dedupe_raw = _get(item, "dedupe_key", "segment_id", "turn_id", "event_id")
    return SpeakerAudioObservation(
        raw_speaker_label=label,
        audio_source_id=source_id,
        channel_label=channel,
        device_role=_get(item, "device_role"),
        route=_get(item, "route"),
        attribution_confidence=_get(item, "attribution_confidence", "source_confidence", "confidence") or 0.0,
        source=_norm_obs_source(_get(item, "attribution_source", "source_kind", "observation_source", "source")
                                or "segment_metadata"),
        source_is_isolated=bool(_get(item, "source_is_isolated", "isolated", "isolated_source") or False),
        turn_index=_get(item, "turn_index", "turn"),
        dedupe_key=(str(dedupe_raw) if dedupe_raw is not None else None),
    )


def _obs_from_label_value(label: Any, token: Any, *, kind: str) -> Optional[SpeakerAudioObservation]:
    """audio_source_metadata/channel_metadata контейнер: label→token. Трактуем как явную
    runtime-metadata (isolated, conf 0.9), чтобы создать стабильный link (как Stage 6)."""
    tok = normalize_audio_token(token)
    if not tok or not label:
        return None
    return SpeakerAudioObservation(
        raw_speaker_label=label,
        audio_source_id=(tok if kind == "audio" else None),
        channel_label=(tok if kind == "channel" else None),
        attribution_confidence=0.9, source="manual_runtime_metadata", source_is_isolated=True,
    )


def _ingest_obs(payload: Any, out: list):
    if payload is None:
        return
    if isinstance(payload, (list, tuple)):
        for it in payload:
            _ingest_obs(it, out)
        return
    if isinstance(payload, dict):
        handled = False
        for key in ("speaker_audio_links", "multi_source", "diarization_metadata", "segment_metadata"):
            if payload.get(key) is not None:
                _ingest_obs(payload[key], out)
                handled = True
        for key, kind in (("audio_source_metadata", "audio"), ("channel_metadata", "channel")):
            sub = payload.get(key)
            if isinstance(sub, dict):
                for lbl, val in sub.items():
                    o = _obs_from_label_value(lbl, val, kind=kind)
                    if o:
                        out.append(o)
                handled = True
        if handled:
            return
        o = _obs_from_item(payload)
        if o:
            out.append(o)
        return
    o = _obs_from_item(payload)
    if o:
        out.append(o)


def extract_speaker_audio_observations_from_payload(payload: Any) -> list[SpeakerAudioObservation]:
    """Извлечь observations из structured payload. Не парсит transcript text; игнорирует
    записи без speaker label и без source/channel."""
    out: list[SpeakerAudioObservation] = []
    _ingest_obs(payload, out)
    return out


# --- tracker ----------------------------------------------------------------

class SpeakerAudioAttributionTracker:
    def __init__(
        self,
        min_observations: int = 2,
        min_dominance_ratio: float = 0.67,
        min_confidence: float = 0.55,
        allow_single_high_confidence_isolated: bool = True,
        single_high_confidence_threshold: float = 0.85,
        allow_single_source_room_mic_links: bool = False,
        max_dedupe_keys: int = 5000,
    ):
        self.min_observations = min_observations
        self.min_dominance_ratio = min_dominance_ratio
        self.min_confidence = min_confidence
        self.allow_single_high_confidence_isolated = allow_single_high_confidence_isolated
        self.single_high_confidence_threshold = single_high_confidence_threshold
        self.allow_single_source_room_mic_links = allow_single_source_room_mic_links
        self.max_dedupe_keys = max_dedupe_keys
        self._observations: list[SpeakerAudioObservation] = []
        self._ambiguous: int = 0
        # Bounded dedupe: одно и то же наблюдение (segment_id) могут увидеть и MeetingRoom,
        # и SessionManager — считать его дважды нельзя (иначе dominance даст ложный link).
        self._seen_dedupe_keys: set[str] = set()
        self._seen_order: list[str] = []
        self._dedupe_seen_count: int = 0

    def clear(self) -> None:
        self._observations.clear()
        self._ambiguous = 0
        self._seen_dedupe_keys.clear()
        self._seen_order.clear()
        self._dedupe_seen_count = 0

    def _coerce(self, observation: Any) -> Optional[SpeakerAudioObservation]:
        if isinstance(observation, SpeakerAudioObservation):
            if observation.raw_speaker_label == "unknown_speaker":
                return None
            if not (observation.audio_source_id or observation.channel_label):
                return None
            return observation
        return _obs_from_item(observation)

    def observe(self, observation: Any) -> bool:
        o = self._coerce(observation)
        if o is None:
            return False
        if o.dedupe_key:
            if o.dedupe_key in self._seen_dedupe_keys:
                self._dedupe_seen_count += 1
                return False  # уже видели это наблюдение
            self._seen_dedupe_keys.add(o.dedupe_key)
            self._seen_order.append(o.dedupe_key)
            if len(self._seen_order) > self.max_dedupe_keys:
                old = self._seen_order.pop(0)
                self._seen_dedupe_keys.discard(old)
        self._observations.append(o)
        return True

    def observe_many(self, observations: Iterable[Any]) -> int:
        return sum(1 for o in observations if self.observe(o))

    def _decide_link(self, obs: list[SpeakerAudioObservation]):
        """→ SpeakerAudioLink | "ambiguous" | None."""
        raw = obs[0].raw_speaker_label
        total = len(obs)
        avg_conf = sum(o.attribution_confidence for o in obs) / total if total else 0.0
        link_source = _OBS_TO_LINK_SOURCE.get(
            Counter(o.source for o in obs).most_common(1)[0][0], "meeting_room_metadata")

        # Rule B: одно isolated high-confidence наблюдение
        if total == 1:
            o = obs[0]
            if (self.allow_single_high_confidence_isolated and o.source_is_isolated
                    and o.attribution_confidence >= self.single_high_confidence_threshold):
                return make_speaker_audio_link(
                    raw, audio_source_id=o.audio_source_id, channel_label=o.channel_label,
                    confidence=o.attribution_confidence, source=link_source)
            # single-source room mic → не создаём link
            if (not o.source_is_isolated and is_generic_room_source_token(o.audio_source_id)
                    and not self.allow_single_source_room_mic_links):
                return None
            return None  # одного наблюдения недостаточно (нужно Rule A или B)

        # Rule A: dominance по нескольким наблюдениям
        if total < self.min_observations:
            return None
        src_counts = Counter(o.audio_source_id for o in obs if o.audio_source_id)
        chan_counts = Counter(o.channel_label for o in obs if o.channel_label)
        dom_src, dom_src_n = src_counts.most_common(1)[0] if src_counts else (None, 0)
        dom_chan, dom_chan_n = chan_counts.most_common(1)[0] if chan_counts else (None, 0)
        src_ratio = dom_src_n / total if dom_src else 0.0
        chan_ratio = dom_chan_n / total if dom_chan else 0.0

        link_src = dom_src if src_ratio >= self.min_dominance_ratio else None
        link_chan = dom_chan if chan_ratio >= self.min_dominance_ratio else None
        if not link_src and not link_chan:
            return "ambiguous"  # конфликт sources/channels без доминанты

        best_ratio = max(src_ratio, chan_ratio)
        link_conf = min(1.0, avg_conf * best_ratio)
        if link_conf < self.min_confidence:
            link_conf = self.min_confidence
        return make_speaker_audio_link(
            raw, audio_source_id=link_src, channel_label=link_chan,
            confidence=link_conf, source=link_source)

    def build_link_map(self) -> SpeakerAudioLinkMap:
        by_sid: dict[str, list] = {}
        for o in self._observations:
            by_sid.setdefault(o.stable_id, []).append(o)
        links: list[SpeakerAudioLink] = []
        self._ambiguous = 0
        for obs in by_sid.values():
            decision = self._decide_link(obs)
            if decision == "ambiguous":
                self._ambiguous += 1
            elif decision is not None:
                links.append(decision)
        return build_speaker_audio_link_map(links)

    def get_stats(self) -> SpeakerAudioAttributionStats:
        link_map = self.build_link_map()  # обновляет self._ambiguous
        distinct = {o.stable_id for o in self._observations}
        return SpeakerAudioAttributionStats(
            observation_count=len(self._observations),
            stable_link_count=link_map.linked_speaker_count,
            speaker_count_observed=len(distinct),
            ambiguous_speaker_count=self._ambiguous,
            average_link_confidence=link_map.average_confidence,
            by_observation_source=dict(Counter(o.source for o in self._observations)),
            by_link_source=dict(link_map.source_summary),
            dedupe_seen_count=self._dedupe_seen_count,
        )
