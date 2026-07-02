"""Speaker Identity Graph v1 (Этап 4) — внутренний слой нормализации ролей спикеров.

Разводит три разных понятия:
- device_role  — технический источник (desktop/phone/secondary/observer), НЕ сторона.
- speaker_side — переговорная сторона (our_side/counterparty/third_party/unknown).
- functional_role — функция участника (decision_maker/engineer/procurement/...).

Legacy self/opponent остаётся рабочим: self→our_side, opponent→counterparty.
Никакого угадывания: неясно → side="unknown", низкий confidence.
"""

import hashlib
import re
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, field_validator

SpeakerSide = Literal["our_side", "counterparty", "third_party", "unknown"]

SpeakerIdentitySource = Literal[
    "manual_correction",
    "legacy_role",
    "audio_channel",
    "diarization",
    "device_role",
    "meeting_context",
    "llm_context",
    "transcript_label",
    "unknown",
]

FunctionalRole = Literal[
    "decision_maker",
    "project_manager",
    "engineer",
    "technical_supervisor",
    "procurement",
    "legal",
    "finance",
    "sales",
    "contractor",
    "customer",
    "observer",
    "unknown",
]

# Приоритет источников при merge (выше = надёжнее)
_SOURCE_PRIORITY = {
    "manual_correction": 100,
    "meeting_context": 70,
    "legacy_role": 60,
    "diarization": 40,
    "audio_channel": 35,
    "llm_context": 30,
    "device_role": 20,
    "transcript_label": 10,
    "unknown": 0,
}

_SIDE_ALIASES = {
    "self": "our_side", "me": "our_side", "us": "our_side", "our": "our_side",
    "ours": "our_side", "we": "our_side", "our_side": "our_side",
    "мы": "our_side", "наша сторона": "our_side", "наши": "our_side", "наша": "our_side",
    "opponent": "counterparty", "counterparty": "counterparty", "not_self": "counterparty",
    "not_us": "counterparty", "not_we": "counterparty", "them": "counterparty",
    "they": "counterparty", "client": "counterparty", "customer": "counterparty",
    "заказчик": "counterparty", "оппонент": "counterparty", "не мы": "counterparty",
    "third_party": "third_party", "observer": "third_party", "external": "third_party",
    "third": "third_party", "третья сторона": "third_party", "наблюдатель": "third_party",
}

_FUNCTIONAL_ALIASES = {
    "decision_maker": "decision_maker", "decision-maker": "decision_maker", "lpr": "decision_maker",
    "project_manager": "project_manager", "pm": "project_manager", "рп": "project_manager",
    "engineer": "engineer", "инженер": "engineer",
    "technical_supervisor": "technical_supervisor", "technadzor": "technical_supervisor",
    "технадзор": "technical_supervisor",
    "procurement": "procurement", "снаб": "procurement", "закупки": "procurement",
    "legal": "legal", "юрист": "legal",
    "finance": "finance", "финансы": "finance", "бухгалтерия": "finance",
    "sales": "sales", "продажи": "sales",
    "contractor": "contractor", "подрядчик": "contractor",
    "customer": "customer", "заказчик": "customer",
    "observer": "observer", "наблюдатель": "observer",
}

_ALLOWED_SIDES = {"our_side", "counterparty", "third_party", "unknown"}
_ALLOWED_FUNCTIONAL = set(_FUNCTIONAL_ALIASES.values()) | {"unknown"}
_ALLOWED_SOURCES = {
    "manual_correction", "legacy_role", "audio_channel", "diarization", "device_role",
    "meeting_context", "llm_context", "transcript_label", "unknown",
}
# Источники, считающиеся «явным hint» (для агрегата hint_source_count)
_HINT_SOURCES = {"manual_correction", "audio_channel", "meeting_context"}


def _clamp01(v: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return max(0.0, min(1.0, f))


def normalize_speaker_label(label: Optional[str]) -> str:
    """Нормализовать метку спикера (схлопнуть пробелы). Пусто → 'unknown_speaker'."""
    if label is None:
        return "unknown_speaker"
    s = re.sub(r"\s+", " ", str(label)).strip()
    return s or "unknown_speaker"


def make_stable_speaker_id(label: Optional[str]) -> str:
    """Стабильный id для метки спикера (slug + короткий hash). НЕ зависит от display_name."""
    norm = normalize_speaker_label(label).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", norm).strip("_")[:24]
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}" if slug else f"spk_{digest}"


def normalize_side(value: Optional[str]) -> SpeakerSide:
    """Свести значение/alias/legacy к SpeakerSide. Неизвестное → 'unknown'."""
    if not value:
        return "unknown"
    s = str(value).strip().lower()
    if s in _ALLOWED_SIDES:
        return s  # type: ignore[return-value]
    return _SIDE_ALIASES.get(s, "unknown")  # type: ignore[return-value]


def side_to_legacy(side: SpeakerSide) -> str:
    """Свести SpeakerSide к legacy self/opponent (для совместимости)."""
    return {
        "our_side": "self",
        "counterparty": "opponent",
        "third_party": "opponent",
        "unknown": "unknown",
    }.get(side, "unknown")


def normalize_functional_role(value: Optional[str]) -> FunctionalRole:
    """Свести значение к FunctionalRole. Неизвестное → 'unknown'."""
    if not value:
        return "unknown"
    s = str(value).strip().lower()
    if s in _ALLOWED_FUNCTIONAL:
        return s  # type: ignore[return-value]
    return _FUNCTIONAL_ALIASES.get(s, "unknown")  # type: ignore[return-value]


def normalize_speaker_identity_source(value: Optional[str]) -> SpeakerIdentitySource:
    """Свести значение к SpeakerIdentitySource. Недопустимое → 'unknown'."""
    if not value:
        return "unknown"
    s = str(value).strip().lower()
    return s if s in _ALLOWED_SOURCES else "unknown"  # type: ignore[return-value]


class SpeakerIdentity(BaseModel):
    raw_speaker_label: str = "unknown_speaker"
    stable_id: str = ""
    display_name: Optional[str] = None
    organization: Optional[str] = None
    side: SpeakerSide = "unknown"
    functional_role: FunctionalRole = "unknown"
    confidence: float = 0.0
    source: SpeakerIdentitySource = "unknown"
    evidence: list[str] = []
    device_role: Optional[str] = None
    channel_label: Optional[str] = None
    last_seen_turn_index: Optional[int] = None

    @field_validator("raw_speaker_label", mode="before")
    @classmethod
    def _norm_label(cls, v):
        return normalize_speaker_label(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_conf(cls, v):
        return _clamp01(v)

    def model_post_init(self, __context) -> None:
        if not self.stable_id:
            self.stable_id = make_stable_speaker_id(self.raw_speaker_label)


class SpeakerIdentityMap(BaseModel):
    speakers: dict[str, SpeakerIdentity] = {}
    version: str = "speaker_identity_v1"
    source_summary: dict[str, int] = {}
    side_counts: dict[str, int] = {}
    average_confidence: float = 0.0


def merge_speaker_identity(existing: SpeakerIdentity, incoming: SpeakerIdentity) -> SpeakerIdentity:
    """Слить две identity одного спикера: приоритет у более надёжного источника/уверенности.

    manual_correction всегда приоритетнее legacy/audio/diarization. evidence объединяется
    без дублей, confidence clamp.
    """
    ep = _SOURCE_PRIORITY.get(existing.source, 0)
    ip = _SOURCE_PRIORITY.get(incoming.source, 0)
    # победитель по (приоритет источника, confidence)
    winner, loser = (incoming, existing) if (ip, incoming.confidence) > (ep, existing.confidence) else (existing, incoming)

    merged_evidence: list[str] = []
    for e in list(existing.evidence) + list(incoming.evidence):
        if e and e not in merged_evidence:
            merged_evidence.append(e)

    # side/functional_role берём у победителя, но если у победителя unknown — добираем у проигравшего
    side = winner.side if winner.side != "unknown" else loser.side
    func = winner.functional_role if winner.functional_role != "unknown" else loser.functional_role

    return SpeakerIdentity(
        raw_speaker_label=winner.raw_speaker_label or existing.raw_speaker_label,
        stable_id=existing.stable_id or winner.stable_id,
        display_name=winner.display_name or loser.display_name,
        organization=winner.organization or loser.organization,
        side=side,
        functional_role=func,
        confidence=_clamp01(max(existing.confidence, incoming.confidence)),
        source=winner.source,
        evidence=merged_evidence,
        device_role=winner.device_role or loser.device_role,
        channel_label=winner.channel_label or loser.channel_label,
        last_seen_turn_index=(
            max(x for x in (existing.last_seen_turn_index, incoming.last_seen_turn_index) if x is not None)
            if (existing.last_seen_turn_index is not None or incoming.last_seen_turn_index is not None)
            else None
        ),
    )


def build_speaker_identity_map(identities: Iterable[SpeakerIdentity]) -> SpeakerIdentityMap:
    """Собрать карту по stable_id, сливая дубли. Считает агрегаты (side/source/avg conf)."""
    speakers: dict[str, SpeakerIdentity] = {}
    for ident in identities:
        key = ident.stable_id or make_stable_speaker_id(ident.raw_speaker_label)
        if key in speakers:
            speakers[key] = merge_speaker_identity(speakers[key], ident)
        else:
            speakers[key] = ident

    side_counts: dict[str, int] = {}
    source_summary: dict[str, int] = {}
    total_conf = 0.0
    for s in speakers.values():
        side_counts[s.side] = side_counts.get(s.side, 0) + 1
        source_summary[s.source] = source_summary.get(s.source, 0) + 1
        total_conf += s.confidence
    avg_conf = round(total_conf / len(speakers), 4) if speakers else 0.0

    return SpeakerIdentityMap(
        speakers=speakers,
        side_counts=side_counts,
        source_summary=source_summary,
        average_confidence=avg_conf,
    )


def build_speaker_context_text(speaker_map: SpeakerIdentityMap, max_speakers: int = 12) -> str:
    """Компактный текст ролей для LLM. Пустая карта → 'Speaker roles are unknown.'."""
    if not speaker_map.speakers:
        return "Speaker roles are unknown."
    lines: list[str] = []
    for ident in list(speaker_map.speakers.values())[:max_speakers]:
        lines.append(
            f"Speaker {ident.raw_speaker_label}: side={ident.side}, "
            f"functional_role={ident.functional_role}, "
            f"confidence={round(ident.confidence, 2)}, source={ident.source}"
        )
    return "\n".join(lines)


def speaker_identity_stats(speaker_map: SpeakerIdentityMap, audio_link_map=None) -> dict:
    """Только безопасные агрегаты по графу (без имён/меток/организаций).

    audio_link_map (SpeakerAudioLinkMap, опц.) добавляет агрегаты по audio/channel-линкам.
    """
    speakers = speaker_map.speakers
    unknown = sum(1 for s in speakers.values() if s.side == "unknown")
    hint_count = sum(1 for s in speakers.values()
                     if s.source in _HINT_SOURCES and s.confidence > 0)
    stats = {
        "speaker_side_counts": dict(speaker_map.side_counts),
        "speaker_sources": dict(speaker_map.source_summary),
        "speaker_average_confidence": speaker_map.average_confidence,
        "speaker_count": len(speakers),
        "unknown_side_count": unknown,
        "hint_source_count": hint_count,
    }
    if audio_link_map is not None:
        stats["audio_linked_speaker_count"] = getattr(audio_link_map, "audio_source_count", 0)
        stats["channel_linked_speaker_count"] = getattr(audio_link_map, "channel_label_count", 0)
        stats["audio_link_average_confidence"] = getattr(audio_link_map, "average_confidence", 0.0)
        stats["audio_link_source_summary"] = dict(getattr(audio_link_map, "source_summary", {}) or {})
    return stats


# --- speaker_identity_hints: нормализация hidden per-meeting override (Этап 5) ----

# Группы hidden-hints и их политики уверенности/источника по умолчанию.
_HINT_GROUPS = {
    "speaker_labels": {"default_conf": 0.9, "max_conf": 0.98, "default_source": "manual_correction"},
    "stable_ids":     {"default_conf": 0.9, "max_conf": 0.98, "default_source": "manual_correction"},
    "audio_sources":  {"default_conf": 0.75, "max_conf": 0.85, "default_source": "audio_channel"},
    "channel_labels": {"default_conf": 0.75, "max_conf": 0.85, "default_source": "audio_channel"},
}
_HINT_EVIDENCE_MAX_LEN = 120
_HINT_EVIDENCE_MAX_ITEMS = 10


def _normalize_hint_entry(hint: dict, cfg: dict) -> dict:
    """Нормализовать один hint в компактный безопасный вид. PII (имя/орг) не принимаем."""
    side = normalize_side(hint.get("side"))
    func = normalize_functional_role(hint.get("functional_role"))

    raw_conf = hint.get("confidence", cfg["default_conf"])
    try:
        conf = float(raw_conf)
    except (TypeError, ValueError):
        conf = cfg["default_conf"]
    conf = max(0.0, min(cfg["max_conf"], conf))
    # пустая/unknown сторона не должна стать уверенным назначением
    if side == "unknown":
        conf = 0.0

    source = normalize_speaker_identity_source(hint.get("source"))
    if source == "unknown":
        source = cfg["default_source"]

    evidence: list[str] = []
    raw_ev = hint.get("evidence")
    if isinstance(raw_ev, (list, tuple)):
        for e in raw_ev[:_HINT_EVIDENCE_MAX_ITEMS]:
            if isinstance(e, str) and e.strip():
                evidence.append(e.strip()[:_HINT_EVIDENCE_MAX_LEN])

    return {"side": side, "functional_role": func, "confidence": conf,
            "source": source, "evidence": evidence}


def normalize_identity_hints(value) -> Optional[dict]:
    """Провалидировать/нормализовать speaker_identity_hints. None→None, non-dict→ValueError.

    Возвращает компактный безопасный dict только из известных групп; если ничего
    валидного — None (нет эффективного override). display_name/organization/raw_speaker_label
    внутри hint игнорируются (без PII в snapshot).
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("speaker_identity_hints должен быть объектом или null")
    out: dict = {}
    for group, cfg in _HINT_GROUPS.items():
        raw_group = value.get(group)
        if not isinstance(raw_group, dict):
            continue
        norm_group: dict = {}
        for key, hint in raw_group.items():
            k = str(key).strip()
            if not k or not isinstance(hint, dict):
                continue
            norm_group[k] = _normalize_hint_entry(hint, cfg)
        if norm_group:
            out[group] = norm_group
    return out or None
