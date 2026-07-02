"""Speaker ↔ audio source / channel links (Этап 6).

Безопасно нормализует structured metadata «speaker label → audio source id / channel label»
из разных форматов проекта, чтобы Speaker Identity Graph мог применить audio_sources /
channel_labels hints ТОЛЬКО при наличии явной связи. Никакого парсинга transcript text,
никакого вывода стороны из «primary»/«desktop». Имена/raw labels не логируются.
"""

import re
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, field_validator

from .speaker_identity import make_stable_speaker_id, normalize_speaker_label

_TOKEN_MAX_LEN = 80

SpeakerAudioLinkSource = Literal[
    "audio_source_metadata",
    "channel_metadata",
    "diarization_metadata",
    "meeting_room_metadata",
    "transcript_metadata",
    "unknown",
]
_ALLOWED_LINK_SOURCES = {
    "audio_source_metadata", "channel_metadata", "diarization_metadata",
    "meeting_room_metadata", "transcript_metadata", "unknown",
}

# Контейнерные ключи (формат C)
_AUDIO_CONTAINERS = ("speaker_sources", "source_by_speaker")
_CHANNEL_CONTAINERS = ("speaker_channels", "channel_by_speaker")
_LIST_CONTAINER = "speaker_audio_links"
_CONTAINER_KEYS = set(_AUDIO_CONTAINERS) | set(_CHANNEL_CONTAINERS) | {_LIST_CONTAINER}


def _clamp01(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return max(0.0, min(1.0, f))


# Generic room/shared-source токены: общий микрофон комнаты/устройство, НЕ per-speaker источник.
# Используется ТОЛЬКО для осторожности attribution (Этап 7), НЕ для вывода стороны.
_GENERIC_ROOM_SOURCE_TOKENS = {
    "primary", "desktop", "phone", "default", "room", "mono", "laptop",
    "microphone", "mic", "browser", "unknown",
}


def is_generic_room_source_token(token: Optional[str]) -> bool:
    """True для общих room/shared-source токенов (primary/desktop/phone/...). НЕ side inference."""
    if not token:
        return False
    return str(token).strip().lower() in _GENERIC_ROOM_SOURCE_TOKENS


def normalize_audio_token(value: Any) -> Optional[str]:
    """Короткий безопасный технический id (source/channel/device/route). Пусто → None."""
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value)).strip()
    if not s:
        return None
    return s[:_TOKEN_MAX_LEN]


def _normalize_link_source(value: Any) -> SpeakerAudioLinkSource:
    if not value:
        return "unknown"
    s = str(value).strip().lower()
    return s if s in _ALLOWED_LINK_SOURCES else "unknown"  # type: ignore[return-value]


class SpeakerAudioLink(BaseModel):
    raw_speaker_label: str = "unknown_speaker"
    stable_id: str = ""
    audio_source_id: Optional[str] = None
    channel_label: Optional[str] = None
    device_role: Optional[str] = None
    route: Optional[str] = None
    confidence: float = 0.0
    source: SpeakerAudioLinkSource = "unknown"

    @field_validator("raw_speaker_label", mode="before")
    @classmethod
    def _norm_label(cls, v):
        return normalize_speaker_label(v)

    @field_validator("audio_source_id", "channel_label", "device_role", "route", mode="before")
    @classmethod
    def _norm_token(cls, v):
        return normalize_audio_token(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_conf(cls, v):
        return _clamp01(v)

    def model_post_init(self, __context) -> None:
        if not self.stable_id:
            self.stable_id = make_stable_speaker_id(self.raw_speaker_label)


class SpeakerAudioLinkMap(BaseModel):
    links_by_stable_id: dict[str, SpeakerAudioLink] = {}
    source_summary: dict[str, int] = {}
    audio_source_count: int = 0
    channel_label_count: int = 0
    linked_speaker_count: int = 0
    average_confidence: float = 0.0


def make_speaker_audio_link(
    raw_speaker_label: Any,
    *,
    audio_source_id: Any = None,
    channel_label: Any = None,
    device_role: Any = None,
    route: Any = None,
    confidence: Any = 0.0,
    source: Any = "unknown",
) -> SpeakerAudioLink:
    return SpeakerAudioLink(
        raw_speaker_label=raw_speaker_label,
        stable_id=make_stable_speaker_id(normalize_speaker_label(raw_speaker_label)),
        audio_source_id=audio_source_id,
        channel_label=channel_label,
        device_role=device_role,
        route=route,
        confidence=confidence,
        source=_normalize_link_source(source),
    )


def _merge_link(a: SpeakerAudioLink, b: SpeakerAudioLink) -> SpeakerAudioLink:
    """Слить два link одного спикера (source+channel из разной metadata)."""
    src = a.source if a.source != "unknown" else b.source
    return SpeakerAudioLink(
        raw_speaker_label=a.raw_speaker_label or b.raw_speaker_label,
        stable_id=a.stable_id or b.stable_id,
        audio_source_id=a.audio_source_id or b.audio_source_id,
        channel_label=a.channel_label or b.channel_label,
        device_role=a.device_role or b.device_role,
        route=a.route or b.route,
        confidence=max(a.confidence, b.confidence),
        source=src,
    )


def build_speaker_audio_link_map(links: Iterable[SpeakerAudioLink]) -> SpeakerAudioLinkMap:
    by_sid: dict[str, SpeakerAudioLink] = {}
    for link in links:
        # link нужен только если есть хоть какая-то аудио/канал-привязка
        if not (link.audio_source_id or link.channel_label):
            continue
        sid = link.stable_id or make_stable_speaker_id(link.raw_speaker_label)
        by_sid[sid] = _merge_link(by_sid[sid], link) if sid in by_sid else link

    source_summary: dict[str, int] = {}
    audio_n = channel_n = 0
    total_conf = 0.0
    for lk in by_sid.values():
        source_summary[lk.source] = source_summary.get(lk.source, 0) + 1
        if lk.audio_source_id:
            audio_n += 1
        if lk.channel_label:
            channel_n += 1
        total_conf += lk.confidence
    avg = round(total_conf / len(by_sid), 4) if by_sid else 0.0

    return SpeakerAudioLinkMap(
        links_by_stable_id=by_sid,
        source_summary=source_summary,
        audio_source_count=audio_n,
        channel_label_count=channel_n,
        linked_speaker_count=len(by_sid),
        average_confidence=avg,
    )


# --- извлечение из разных форматов metadata ---------------------------------

def _get(item: Any, *names: str):
    for n in names:
        v = item.get(n) if isinstance(item, dict) else getattr(item, n, None)
        if v is not None:
            return v
    return None


def _link_from_item(item: Any, default_source: str) -> Optional[SpeakerAudioLink]:
    """Формат D/E: dict/object с speaker_label + source/channel/..."""
    if item is None:
        return None
    label = _get(item, "speaker_label", "speaker", "label", "raw_speaker_label")
    if not label:
        return None
    source_id = _get(item, "audio_source_id", "source_id", "source")
    channel = _get(item, "channel_label", "channel")
    if not source_id and not channel:
        return None
    src = "audio_source_metadata" if source_id else "channel_metadata"
    return make_speaker_audio_link(
        label, audio_source_id=source_id, channel_label=channel,
        device_role=_get(item, "device_role"), route=_get(item, "route"),
        confidence=_get(item, "confidence") or 0.0, source=src,
    )


def _ingest(meta: Any, *, default_kind: str, default_source: str, sink: list):
    """Разобрать один объект metadata (dict/list/object) в links → sink."""
    if meta is None:
        return
    if isinstance(meta, dict):
        # формат C: контейнеры
        if any(k in meta for k in _CONTAINER_KEYS):
            for k in _AUDIO_CONTAINERS:
                sub = meta.get(k)
                if isinstance(sub, dict):
                    for lbl, val in sub.items():
                        tok = normalize_audio_token(val)
                        if tok:
                            sink.append(make_speaker_audio_link(
                                lbl, audio_source_id=tok, source="audio_source_metadata"))
            for k in _CHANNEL_CONTAINERS:
                sub = meta.get(k)
                if isinstance(sub, dict):
                    for lbl, val in sub.items():
                        tok = normalize_audio_token(val)
                        if tok:
                            sink.append(make_speaker_audio_link(
                                lbl, channel_label=tok, source="channel_metadata"))
            lst = meta.get(_LIST_CONTAINER)
            if isinstance(lst, (list, tuple)):
                for it in lst:
                    lk = _link_from_item(it, default_source)
                    if lk:
                        sink.append(lk)
            return
        # формат A/B: plain dict label -> str|object
        for lbl, val in meta.items():
            if isinstance(val, dict):
                lk = _link_from_item({**val, "speaker_label": lbl}, default_source)
                if lk:
                    sink.append(lk)
            else:
                tok = normalize_audio_token(val)
                if not tok:
                    continue
                if default_kind == "channel":
                    sink.append(make_speaker_audio_link(lbl, channel_label=tok, source="channel_metadata"))
                else:
                    sink.append(make_speaker_audio_link(lbl, audio_source_id=tok, source="audio_source_metadata"))
        return
    if isinstance(meta, (list, tuple)):
        for it in meta:
            lk = _link_from_item(it, default_source)
            if lk:
                sink.append(lk)
        return
    # одиночный объект (формат E)
    lk = _link_from_item(meta, default_source)
    if lk:
        sink.append(lk)


def extract_audio_links_from_metadata(
    *,
    audio_source_metadata: Any = None,
    channel_metadata: Any = None,
    recent_dialog: str = "",
) -> SpeakerAudioLinkMap:
    """Собрать SpeakerAudioLinkMap из structured metadata. Без парсинга transcript text.

    recent_dialog НЕ используется как источник линков (только structured metadata).
    """
    sink: list[SpeakerAudioLink] = []
    _ingest(audio_source_metadata, default_kind="audio",
            default_source="audio_source_metadata", sink=sink)
    _ingest(channel_metadata, default_kind="channel",
            default_source="channel_metadata", sink=sink)
    return build_speaker_audio_link_map(sink)
