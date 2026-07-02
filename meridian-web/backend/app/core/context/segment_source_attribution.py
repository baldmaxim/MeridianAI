"""Committed segment source attribution (Этап 8).

Безопасно извлекает structured «зону записи» (audio_source_id/channel_label/source_kind/
isolated) из committed transcript segment и решает, можно ли создать speaker→audio observation.

Ключевой safety rule: общий primary room-mic (source_kind=room_mic / generic-токен,
source_is_isolated=false) НЕ даёт observation — иначе все спикеры улетят на primary.
Сторона/личность здесь НЕ выводятся. transcript text / display_name / organization не хранятся.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, field_validator

from .speaker_audio_links import is_generic_room_source_token, normalize_audio_token
from .speaker_identity import normalize_speaker_label

_MIN_EMIT_CONFIDENCE = 0.55

AttributionSourceT = Literal[
    "committed_segment",
    "diarization_result",
    "multi_source_segment",
    "secondary_shadow_segment",
    "manual_runtime_metadata",
    "unknown",
]
_ALLOWED_ATTR_SOURCES = {
    "committed_segment", "diarization_result", "multi_source_segment",
    "secondary_shadow_segment", "manual_runtime_metadata", "unknown",
}
SourceKindT = Literal[
    "room_mic", "isolated_source", "multi_channel", "secondary_shadow", "manual", "unknown",
]
_ALLOWED_SOURCE_KINDS = {
    "room_mic", "isolated_source", "multi_channel", "secondary_shadow", "manual", "unknown",
}
_NON_ROOM_KINDS = {"isolated_source", "multi_channel", "secondary_shadow", "manual"}
_TRUSTED_ATTR_SOURCES = {
    "diarization_result", "multi_source_segment", "secondary_shadow_segment", "manual_runtime_metadata",
}

# attribution_source (Этап 8) → observation source (Этап 7 literal)
_ATTR_TO_OBS_SOURCE = {
    "multi_source_segment": "multi_source_ingest",
    "secondary_shadow_segment": "secondary_shadow",
    "diarization_result": "diarization_metadata",
    "manual_runtime_metadata": "manual_runtime_metadata",
    "committed_segment": "segment_metadata",
    "unknown": "unknown",
}

_NESTED_KEYS = ("source_attribution", "audio_attribution", "segment_metadata",
                "diarization_metadata", "multi_source")


def _clamp01(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:
        return 0.0
    return max(0.0, min(1.0, f))


class SegmentSourceAttribution(BaseModel):
    speaker_label: Optional[str] = None
    audio_source_id: Optional[str] = None
    channel_label: Optional[str] = None
    device_role: Optional[str] = None
    route: Optional[str] = None
    attribution_confidence: float = 0.0
    source_is_isolated: bool = False
    attribution_source: AttributionSourceT = "unknown"
    source_kind: SourceKindT = "unknown"
    turn_index: Optional[int] = None

    @field_validator("speaker_label", mode="before")
    @classmethod
    def _norm_label(cls, v):
        if v is None:
            return None
        n = normalize_speaker_label(v)
        return None if n == "unknown_speaker" else n

    @field_validator("audio_source_id", "channel_label", "device_role", "route", mode="before")
    @classmethod
    def _norm_token(cls, v):
        return normalize_audio_token(v)

    @field_validator("attribution_confidence", mode="before")
    @classmethod
    def _clamp_conf(cls, v):
        return _clamp01(v)

    @field_validator("attribution_source", mode="before")
    @classmethod
    def _norm_attr_source(cls, v):
        s = str(v).strip().lower() if v else "unknown"
        return s if s in _ALLOWED_ATTR_SOURCES else "unknown"

    @field_validator("source_kind", mode="before")
    @classmethod
    def _norm_kind(cls, v):
        s = str(v).strip().lower() if v else "unknown"
        return s if s in _ALLOWED_SOURCE_KINDS else "unknown"


def _get_raw(item: Any, name: str):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _get(nested: Any, segment: Any, *names: str):
    for n in names:
        if isinstance(nested, dict) and nested.get(n) is not None:
            return nested.get(n)
    for n in names:
        v = _get_raw(segment, n)
        if v is not None:
            return v
    return None


def extract_segment_source_attribution(segment: Any) -> Optional[SegmentSourceAttribution]:
    """Извлечь SegmentSourceAttribution из segment (dict/object). None без speaker_label.

    Учитывает вложенные контейнеры (source_attribution/audio_attribution/segment_metadata/
    diarization_metadata/multi_source). Не читает transcript/text/recent_dialog. Сторона не выводится."""
    if segment is None:
        return None
    nested = None
    for key in _NESTED_KEYS:
        v = _get_raw(segment, key)
        if isinstance(v, dict):
            nested = v
            break
    label = _get(nested, segment, "speaker_label", "speaker", "label", "raw_speaker_label")
    if not label:
        return None
    return SegmentSourceAttribution(
        speaker_label=label,
        audio_source_id=_get(nested, segment, "audio_source_id", "source_id", "source",
                             "input_source", "track_id"),
        channel_label=_get(nested, segment, "channel_label", "channel", "channel_name"),
        device_role=_get(nested, segment, "device_role"),
        route=_get(nested, segment, "route"),
        attribution_confidence=_get(nested, segment, "attribution_confidence",
                                    "source_confidence", "confidence") or 0.0,
        source_is_isolated=bool(_get(nested, segment, "source_is_isolated", "isolated",
                                     "isolated_source", "per_speaker_source") or False),
        attribution_source=_get(nested, segment, "attribution_source") or "committed_segment",
        source_kind=_get(nested, segment, "source_kind") or "unknown",
        turn_index=_get(nested, segment, "turn_index", "turn"),
    )


def should_emit_speaker_audio_observation(attribution: Optional[SegmentSourceAttribution]) -> bool:
    """Можно ли создать speaker→audio observation. Conservative: общий room-mic → False."""
    if attribution is None or not attribution.speaker_label:
        return False
    if not attribution.audio_source_id and not attribution.channel_label:
        return False
    # ЖЁСТКИЙ блок ПЕРЕД любым True: общий room-mic / generic-токен без isolation нельзя, даже
    # если source_kind/attribution_source заявлены per-channel (противоречивая metadata → блок).
    if not attribution.source_is_isolated:
        if attribution.source_kind == "room_mic":
            return False
        if is_generic_room_source_token(attribution.audio_source_id):
            return False
    conf = attribution.attribution_confidence
    if attribution.source_is_isolated and conf >= _MIN_EMIT_CONFIDENCE:
        return True
    if attribution.source_kind in _NON_ROOM_KINDS and conf >= _MIN_EMIT_CONFIDENCE:
        return True
    if (attribution.attribution_source in _TRUSTED_ATTR_SOURCES and conf >= _MIN_EMIT_CONFIDENCE
            and attribution.source_kind != "room_mic"):
        return True
    return False


def segment_source_attribution_to_observation_payload(
    attribution: Optional[SegmentSourceAttribution],
) -> Optional[dict]:
    """Payload для Stage 7 extract_speaker_audio_observations_from_payload. None если нельзя.

    Содержит ТОЛЬКО технические поля; стороны нет. source маппится в Stage 7 observation literal."""
    if not should_emit_speaker_audio_observation(attribution):
        return None
    return {
        "speaker_label": attribution.speaker_label,
        "audio_source_id": attribution.audio_source_id,
        "channel_label": attribution.channel_label,
        "device_role": attribution.device_role,
        "route": attribution.route,
        "attribution_confidence": attribution.attribution_confidence,
        "source_is_isolated": attribution.source_is_isolated,
        "source": _ATTR_TO_OBS_SOURCE.get(attribution.attribution_source, "unknown"),
        "turn_index": attribution.turn_index,
    }


def build_observation_payload_from_segment(segment: Any) -> Optional[dict]:
    """Удобный helper: extract → should_emit → payload + dedupe (segment_id). None если нельзя."""
    attr = extract_segment_source_attribution(segment)
    payload = segment_source_attribution_to_observation_payload(attr)
    if payload is None:
        return None
    seg_id = _get_raw(segment, "segment_id") or _get_raw(segment, "id")
    if seg_id:
        payload["segment_id"] = str(seg_id)
    return payload


# --- Этап 9: безопасное построение/привязка source_attribution dict --------

def build_segment_source_attribution_dict(
    *,
    speaker_label: Optional[str] = None,
    audio_source_id: Optional[str] = None,
    channel_label: Optional[str] = None,
    device_role: Optional[str] = None,
    route: Optional[str] = None,
    attribution_confidence: Optional[float] = None,
    source_is_isolated: bool = False,
    attribution_source: str = "unknown",
    source_kind: str = "unknown",
    turn_index: Optional[int] = None,
    segment_id: Optional[str] = None,
) -> Optional[dict]:
    """Построить безопасный source_attribution dict для CommittedSegment.source_attribution.

    Возвращает dict ТОЛЬКО если observation безопасна (should_emit). None для общего primary/
    desktop/phone/room_mic без isolation, без speaker_label или без source/channel. Стороны нет.
    Результат совместим с extract_segment_source_attribution (плоские поля)."""
    attr = SegmentSourceAttribution(
        speaker_label=speaker_label,
        audio_source_id=audio_source_id,
        channel_label=channel_label,
        device_role=device_role,
        route=route,
        attribution_confidence=(attribution_confidence if attribution_confidence is not None else 0.0),
        source_is_isolated=source_is_isolated,
        attribution_source=attribution_source,
        source_kind=source_kind,
        turn_index=turn_index,
    )
    if not should_emit_speaker_audio_observation(attr):
        return None
    out = {
        "speaker_label": attr.speaker_label,
        "audio_source_id": attr.audio_source_id,
        "channel_label": attr.channel_label,
        "device_role": attr.device_role,
        "route": attr.route,
        "attribution_confidence": attr.attribution_confidence,
        "source_is_isolated": attr.source_is_isolated,
        "attribution_source": attr.attribution_source,
        "source_kind": attr.source_kind,
        "turn_index": attr.turn_index,
    }
    if segment_id:
        out["segment_id"] = str(segment_id)  # для dedupe; наружу не сериализуется
    return out


# Технические ключи attribution, которые НИКОГДА не должны утекать во frontend/public payload.
_PUBLIC_STRIP_KEYS = (
    "source_attribution", "audio_source_id", "channel_label", "device_role", "route",
    "source_is_isolated", "attribution_source", "source_kind", "attribution_confidence",
)


def public_committed_segment_payload(segment: Any) -> dict:
    """Публичный wire-payload сегмента БЕЗ technical source attribution (defense-in-depth).

    Берёт segment.to_wire_full() (если есть) или сам dict, затем удаляет technical-ключи.
    Существующие to_wire/to_wire_full/to_dict уже их не включают — это страховка от регрессий."""
    if hasattr(segment, "to_wire_full"):
        d = dict(segment.to_wire_full())
    elif isinstance(segment, dict):
        d = dict(segment)
    else:
        d = {}
    for k in _PUBLIC_STRIP_KEYS:
        d.pop(k, None)
    return d


def attach_source_attribution_to_committed_segment(segment: Any, attribution: Optional[dict]) -> Any:
    """Проставить source_attribution на segment (dataclass/pydantic/object/dict). None → no-op.

    Backward-compatible: не падает на старых объектах; не сериализует наружу автоматически."""
    if attribution is None:
        return segment
    if isinstance(segment, dict):
        segment["source_attribution"] = attribution
        return segment
    try:
        setattr(segment, "source_attribution", attribution)
    except Exception:  # noqa: BLE001 — старый/иммутабельный объект → тихо пропускаем
        pass
    return segment
