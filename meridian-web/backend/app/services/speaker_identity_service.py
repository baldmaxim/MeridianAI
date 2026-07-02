"""SpeakerIdentityService (Этап 4) — runtime-сборка SpeakerIdentityMap без миграций/БД/LLM.

Использует уже доступные in-memory данные (legacy speaker_roles, recent_dialog labels,
опционально device hints). Ничего не угадывает: нет данных → side="unknown".
"""

import re
from typing import Any, Optional

from ..core.context.speaker_identity import (
    SpeakerIdentity,
    SpeakerIdentityMap,
    build_speaker_context_text,
    build_speaker_identity_map,
    make_stable_speaker_id,
    merge_speaker_identity,
    normalize_functional_role,
    normalize_identity_hints,
    normalize_side,
    normalize_speaker_label,
)
from ..core.context.speaker_audio_links import extract_audio_links_from_metadata

_AUDIO_HINT_CONF_CAP = 0.85

# Явные стороны как speaker-label префиксы (диаризационные/служебные).
_SIDE_TOKENS = (
    r"НЕ\s+МЫ|МЫ|OUR_SIDE|US|NOT_US|COUNTERPARTY|OPPONENT|THIRD_PARTY|ТРЕТЬЯ\s+СТОРОНА"
)
# Технические метки спикеров: Speaker N / SPEAKER_N / SM_N / S_N (+ bracket-формы).
_SPK_TOKEN = r"(?:SPEAKER|Speaker|SM|S)\s*_?\s*\d+"

# СТРОГИЕ паттерны (default). Никаких произвольных "Имя:".
_STRICT_LABEL_PATTERNS = [
    re.compile(rf"^\s*\[(?P<label>{_SPK_TOKEN})\]", re.IGNORECASE),
    re.compile(rf"^\s*(?P<label>{_SPK_TOKEN})\s*:", re.IGNORECASE),
    re.compile(rf"^\s*\[(?P<label>{_SIDE_TOKENS})\]", re.IGNORECASE),
    re.compile(rf"^\s*(?P<label>{_SIDE_TOKENS})\s*:", re.IGNORECASE),
]
# Generic — ТОЛЬКО при allow_generic_labels=True (legacy-поведение).
_GENERIC_LABEL_PATTERN = re.compile(r"^\s*(?P<label>[A-Za-zА-Яа-я][\w .\-]{0,30})\s*:")

# Явная сторона по метке: label.lower() → (side, confidence)
_EXPLICIT_SIDE = {
    "мы": ("our_side", 0.9), "our_side": ("our_side", 0.9), "us": ("our_side", 0.9),
    "не мы": ("counterparty", 0.9), "not_us": ("counterparty", 0.9),
    "counterparty": ("counterparty", 0.9), "opponent": ("counterparty", 0.9),
    "third_party": ("third_party", 0.85), "третья сторона": ("third_party", 0.85),
}

_LEGACY_CONF = 0.85
# 0.99 — выше cap speaker_labels hint (0.98), чтобы подтверждённые роли (manual_overrides)
# всегда были приоритетнее явных identity_hints (порядок приоритетов Этапа 5).
_MANUAL_CONF = 0.99
_DEVICE_CONF_CAP = 0.55


def _explicit_side_for_label(raw: str):
    """(side, confidence, source) для метки. Явная сторона → high conf; иначе unknown/0.0."""
    hit = _EXPLICIT_SIDE.get((raw or "").strip().lower())
    if hit:
        return hit[0], hit[1], "transcript_label"
    return "unknown", 0.0, "transcript_label"


def parse_identity_hints(identity_hints):
    """Нормализовать speaker_identity_hints (idempotent на уже-валидированных данных)."""
    try:
        return normalize_identity_hints(identity_hints)
    except ValueError:
        return None


class SpeakerIdentityService:
    """Собирает SpeakerIdentityMap из имеющихся данных. Без БД/LLM на этом этапе."""

    # ---- legacy roles → identities ----

    def build_from_legacy_roles(self, legacy_roles: Any) -> SpeakerIdentityMap:
        return build_speaker_identity_map(self._iter_legacy(legacy_roles, source="legacy_role",
                                                            confidence=_LEGACY_CONF))

    def _iter_legacy(self, legacy_roles: Any, *, source: str, confidence: float):
        """Гибко разобрать текущие структуры ролей в SpeakerIdentity."""
        if not legacy_roles:
            return
        # dict: {label: "self"} ИЛИ {label: {"side":..., "role":...}}
        if isinstance(legacy_roles, dict):
            for label, val in legacy_roles.items():
                ident = self._identity_from_value(label, val, source=source, confidence=confidence)
                if ident is not None:
                    yield ident
            return
        # list объектов/словарей
        if isinstance(legacy_roles, (list, tuple, set)):
            for item in legacy_roles:
                ident = self._identity_from_item(item, source=source, confidence=confidence)
                if ident is not None:
                    yield ident
            return
        # одиночный объект
        ident = self._identity_from_item(legacy_roles, source=source, confidence=confidence)
        if ident is not None:
            yield ident

    def _identity_from_value(self, label, val, *, source: str, confidence: float) -> Optional[SpeakerIdentity]:
        raw = normalize_speaker_label(label)
        if raw == "unknown_speaker" and not val:
            return None
        side_val = val
        role_val = None
        name_val = None
        if isinstance(val, dict):
            side_val = val.get("side") or val.get("role_side") or val.get("value")
            role_val = val.get("functional_role") or val.get("role")
            name_val = val.get("display_name") or val.get("name")
        side = normalize_side(side_val if isinstance(side_val, str) else None)
        return SpeakerIdentity(
            raw_speaker_label=raw,
            stable_id=make_stable_speaker_id(raw),
            display_name=(name_val or None),
            side=side,
            functional_role=normalize_functional_role(role_val if isinstance(role_val, str) else None),
            confidence=confidence if side != "unknown" else min(confidence, 0.4),
            source=source,  # type: ignore[arg-type]
            evidence=[f"{source}:{raw}"],
        )

    def _identity_from_item(self, item, *, source: str, confidence: float) -> Optional[SpeakerIdentity]:
        # объект с атрибутами
        label = (getattr(item, "speaker_label", None) or getattr(item, "label", None)
                 if not isinstance(item, dict) else
                 item.get("speaker_label") or item.get("label"))
        if isinstance(item, dict):
            side_val = item.get("side") or item.get("role_side")
            role_val = item.get("functional_role") or item.get("role")
            name_val = item.get("display_name") or item.get("name")
        else:
            side_val = getattr(item, "side", None) or getattr(item, "role_side", None)
            role_val = getattr(item, "functional_role", None) or getattr(item, "role", None)
            name_val = getattr(item, "display_name", None) or getattr(item, "name", None)
        if not label:
            return None
        raw = normalize_speaker_label(label)
        side = normalize_side(side_val if isinstance(side_val, str) else None)
        return SpeakerIdentity(
            raw_speaker_label=raw,
            stable_id=make_stable_speaker_id(raw),
            display_name=(name_val or None),
            side=side,
            functional_role=normalize_functional_role(role_val if isinstance(role_val, str) else None),
            confidence=confidence if side != "unknown" else min(confidence, 0.4),
            source=source,  # type: ignore[arg-type]
            evidence=[f"{source}:{raw}"],
        )

    # ---- transcript labels ----

    def extract_labels_from_recent_dialog(self, recent_dialog: str, max_labels: int = 20,
                                          allow_generic_labels: bool = False) -> list[str]:
        """Извлечь метки спикеров из строк диалога. Только speaker-label префиксы.

        default (allow_generic_labels=False): НЕ ловит произвольные "Иван:"/"Менеджер:".
        Извлекаются только Speaker N / SM_N / S_N / SPEAKER_N (+ bracket) и явные стороны
        МЫ/НЕ МЫ/OUR_SIDE/US/NOT_US/COUNTERPARTY/OPPONENT/THIRD_PARTY/ТРЕТЬЯ СТОРОНА.
        Это парсинг префиксов, НЕ keyword-trigger логика.
        """
        if not recent_dialog:
            return []
        patterns = list(_STRICT_LABEL_PATTERNS)
        if allow_generic_labels:
            patterns.append(_GENERIC_LABEL_PATTERN)
        out: list[str] = []
        seen: set[str] = set()
        for line in recent_dialog.splitlines():
            if not line.strip():
                continue
            for pat in patterns:
                m = pat.match(line)
                if m:
                    raw = normalize_speaker_label(m.group("label"))
                    if raw != "unknown_speaker" and raw not in seen:
                        seen.add(raw)
                        out.append(raw)
                    break
            if len(out) >= max_labels:
                break
        return out

    # ---- device hints (weak) ----

    def _iter_device_hints(self, device_roles: Any):
        """device/channel — слабый hint. side НЕ выводим автоматически (только unknown)."""
        if not device_roles:
            return
        items = device_roles.items() if isinstance(device_roles, dict) else None
        if items is None:
            return
        for label, dev in items:
            raw = normalize_speaker_label(label)
            if raw == "unknown_speaker":
                continue
            yield SpeakerIdentity(
                raw_speaker_label=raw,
                stable_id=make_stable_speaker_id(raw),
                side="unknown",  # device НЕ определяет переговорную сторону
                confidence=min(_DEVICE_CONF_CAP, 0.5),
                source="device_role",
                device_role=(str(dev) if dev is not None else None),
                evidence=[f"device_role:{raw}"],
            )

    # ---- runtime сборка ----

    def build_runtime_map(
        self,
        *,
        legacy_roles: Any = None,
        recent_dialog: str = "",
        device_roles: Any = None,
        manual_overrides: Any = None,
        identity_hints: Any = None,
        audio_source_metadata: Any = None,
        channel_metadata: Any = None,
        audio_link_map: Any = None,
    ) -> SpeakerIdentityMap:
        """Собрать карту. Приоритет: manual > identity_hints(labels/ids) > legacy >
        audio/channel hints (только через explicit link) > transcript labels > device.
        Конфликты решает merge_speaker_identity по приоритету источника/уверенности.
        """
        identities: list[SpeakerIdentity] = []
        # 1) manual overrides — высший приоритет
        identities.extend(self._iter_legacy(manual_overrides, source="manual_correction",
                                            confidence=_MANUAL_CONF))
        # 2) legacy/persisted roles
        identities.extend(self._iter_legacy(legacy_roles, source="legacy_role", confidence=_LEGACY_CONF))
        # 3) device hints (weak, side=unknown)
        identities.extend(self._iter_device_hints(device_roles))
        # 4) метки из диалога — явная сторона (МЫ/НЕ МЫ/...) или unknown; merge снимет дубли
        for raw in self.extract_labels_from_recent_dialog(recent_dialog):
            side, conf, src = _explicit_side_for_label(raw)
            identities.append(SpeakerIdentity(
                raw_speaker_label=raw, stable_id=make_stable_speaker_id(raw), side=side,
                confidence=conf, source=src, evidence=[f"{src}:{raw}"],
            ))

        base_map = build_speaker_identity_map(identities) if identities else SpeakerIdentityMap()

        # 5) явные hidden hints: speaker_labels/stable_ids
        hints = parse_identity_hints(identity_hints)
        if hints:
            base_map = apply_identity_hints(base_map, hints)
            # 6) audio_sources/channel_labels — ТОЛЬКО через explicit speaker↔source/channel link
            if audio_link_map is None and (audio_source_metadata is not None or channel_metadata is not None):
                audio_link_map = extract_audio_links_from_metadata(
                    audio_source_metadata=audio_source_metadata,
                    channel_metadata=channel_metadata,
                    recent_dialog=recent_dialog,
                )
            if audio_link_map is not None:
                base_map = apply_audio_channel_hints(base_map, hints, audio_link_map)
        return base_map

    def build_context_text(self, speaker_map: SpeakerIdentityMap, max_speakers: int = 12) -> str:
        return build_speaker_context_text(speaker_map, max_speakers=max_speakers)


# --- применение hidden hints к карте ----------------------------------------

def _identity_from_hint(label: str, hint: dict, *, stable_id: str | None = None) -> SpeakerIdentity:
    raw = normalize_speaker_label(label)
    sid = stable_id or make_stable_speaker_id(raw)
    return SpeakerIdentity(
        raw_speaker_label=raw,
        stable_id=sid,
        side=hint.get("side", "unknown"),
        functional_role=hint.get("functional_role", "unknown"),
        confidence=hint.get("confidence", 0.0),
        source=hint.get("source", "manual_correction"),
        evidence=list(hint.get("evidence") or []),
    )


def _merge_into(speakers: dict, ident: SpeakerIdentity, *, key: str | None = None) -> None:
    k = key or ident.stable_id
    speakers[k] = merge_speaker_identity(speakers[k], ident) if k in speakers else ident


def apply_identity_hints(base_map: SpeakerIdentityMap, identity_hints) -> SpeakerIdentityMap:
    """Наложить speaker_labels/stable_ids hints на карту (Этап 5). Возвращает новую карту.

    audio_sources/channel_labels тут НЕ применяются — для них apply_audio_channel_hints
    (только через explicit speaker↔source/channel link).
    """
    hints = parse_identity_hints(identity_hints)
    if not hints:
        return base_map
    speakers = dict(base_map.speakers)

    for label, h in hints.get("speaker_labels", {}).items():
        _merge_into(speakers, _identity_from_hint(label, h))

    for sid, h in hints.get("stable_ids", {}).items():
        raw = speakers[sid].raw_speaker_label if sid in speakers else f"speaker:{sid}"
        _merge_into(speakers, _identity_from_hint(raw, h, stable_id=sid), key=sid)

    return build_speaker_identity_map(list(speakers.values()))


def _resolve_audio_channel(a: dict | None, c: dict | None):
    """Свести audio_source hint (a) и channel hint (c) в (side, role, conf, evidence)|None.

    Учитывает только hints с реальной стороной (side!=unknown). Конфликт разводит по разнице
    confidence (≥0.15 → берём уверенный со штрафом −0.1; иначе unknown, conf=max−0.2)."""
    a = a if (a and a.get("side") != "unknown") else None
    c = c if (c and c.get("side") != "unknown") else None
    if not a and not c:
        return None
    if a and not c:
        return a["side"], a.get("functional_role", "unknown"), a["confidence"], ["audio_source_hint"]
    if c and not a:
        return c["side"], c.get("functional_role", "unknown"), c["confidence"], ["channel_label_hint"]
    # оба присутствуют
    if a["side"] == c["side"]:
        func = a.get("functional_role", "unknown")
        if func == "unknown":
            func = c.get("functional_role", "unknown")
        return a["side"], func, max(a["confidence"], c["confidence"]), ["audio_source_hint", "channel_label_hint"]
    # конфликт сторон
    if abs(a["confidence"] - c["confidence"]) >= 0.15:
        w, tag = (a, "audio_source_hint") if a["confidence"] > c["confidence"] else (c, "channel_label_hint")
        return w["side"], w.get("functional_role", "unknown"), max(0.0, w["confidence"] - 0.1), [
            tag, "conflicting_audio_channel_hints"]
    conf = max(0.0, max(a["confidence"], c["confidence"]) - 0.2)
    return "unknown", "unknown", conf, ["conflicting_audio_channel_hints"]


def apply_audio_channel_hints(base_map: SpeakerIdentityMap, identity_hints,
                              audio_link_map) -> SpeakerIdentityMap:
    """Применить audio_sources/channel_labels hints ЧЕРЕЗ explicit link (Этап 6).

    Для каждого link (speaker↔source/channel) ищем hint по link.audio_source_id /
    link.channel_label. source="audio_channel", confidence cap ≤0.85. Без link — не применяем.
    """
    hints = parse_identity_hints(identity_hints)
    if not hints or audio_link_map is None:
        return base_map
    audio_hints = hints.get("audio_sources", {})
    channel_hints = hints.get("channel_labels", {})
    links = getattr(audio_link_map, "links_by_stable_id", None) or {}
    if (not audio_hints and not channel_hints) or not links:
        return base_map

    speakers = dict(base_map.speakers)
    for sid, link in links.items():
        a = audio_hints.get(link.audio_source_id) if link.audio_source_id else None
        c = channel_hints.get(link.channel_label) if link.channel_label else None
        resolved = _resolve_audio_channel(a, c)
        if resolved is None:
            continue
        side, func, conf, evidence = resolved
        ident = SpeakerIdentity(
            raw_speaker_label=link.raw_speaker_label, stable_id=sid,
            side=side, functional_role=func,
            confidence=min(conf, _AUDIO_HINT_CONF_CAP),
            source="audio_channel", evidence=evidence,
        )
        _merge_into(speakers, ident, key=sid)
    return build_speaker_identity_map(list(speakers.values()))
