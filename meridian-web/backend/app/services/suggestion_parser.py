"""Парсинг/коэрция/safety-проверки структурированных подсказок (Этап 6)."""

import json
import logging
import re

from ..config import get_settings
from ..schemas.suggestion import SuggestionCard, SuggestionResponse

logger = logging.getLogger("meridian.suggestions")

_CATEGORICAL = ("обязан", "по договору", "согласно договор", "по закону", "по контракт", "по закон")
_CONDITIONAL = ("если", "при услови", "в обмен", "взамен", "одновременно фиксир", "при этом фиксир")


def extract_json_from_text(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start:end + 1]
    return None


def fallback_card(reason: str, text: str | None = None) -> SuggestionCard:
    return SuggestionCard(
        type="clarify",
        priority=4,
        title="Нужно уточнить",
        text=text or "Недостаточно данных для уверенной подсказки. Лучше задать уточняющий вопрос.",
        why=reason or "Модель не вернула корректную структуру.",
        evidence=[],
        confidence=0.2,
        needs_user_check=True,
        source_mode="fallback",
    )


def fallback_response(reason: str, raw_text: str | None = None) -> SuggestionResponse:
    return SuggestionResponse(cards=[fallback_card(reason)], raw_text=raw_text, degraded=True)


def parse_suggestion_response(text: str | None, source_mode: str = "auto",
                              model: str | None = None) -> SuggestionResponse | None:
    """Распарсить ответ LLM в SuggestionResponse. None — невалидно (нужен repair/fallback)."""
    js = extract_json_from_text(text)
    if js is None:
        return None
    try:
        data = json.loads(js)
    except (json.JSONDecodeError, ValueError):
        return None

    raw_cards = None
    if isinstance(data, dict) and isinstance(data.get("cards"), list):
        raw_cards = data["cards"]
    elif isinstance(data, list):
        raw_cards = data
    elif isinstance(data, dict) and (data.get("text") or data.get("type")):
        raw_cards = [data]  # один card без обёртки
    if raw_cards is None:
        return None

    cards: list[SuggestionCard] = []
    for rc in raw_cards:
        if not isinstance(rc, dict):
            continue
        try:
            card = SuggestionCard(**rc)
        except Exception:
            continue
        if not card.text.strip():
            continue  # пустые/no-op не сохраняем
        card.source_mode = source_mode
        cards.append(card)

    return SuggestionResponse(cards=cards, raw_text=text, model=model, degraded=False)


def apply_safety_checks(cards: list[SuggestionCard], doc_context_text: str = "") -> list[SuggestionCard]:
    """Детерминированные guard'ы против галлюцинаций (Этап 6, §18)."""
    settings = get_settings()
    require_ev = settings.suggestion_evidence_required_for_high_confidence
    ctx_low = (doc_context_text or "").lower()

    for c in cards:
        has_evidence = len(c.evidence) > 0

        # 1) высокая уверенность без evidence → понизить + проверить
        if require_ev and not has_evidence and c.confidence > 0.65:
            c.confidence = 0.55
            c.needs_user_check = True

        # 2) document-evidence с неизвестным ref → проверить
        for e in c.evidence:
            if e.source == "document":
                name = (e.ref or "").split(",")[0].strip().lower()
                if not name or (ctx_low and name not in ctx_low):
                    c.needs_user_check = True

        # 3) категоричные формулировки без evidence → проверить + ограничить уверенность
        low = (c.text or "").lower()
        if any(w in low for w in _CATEGORICAL) and not has_evidence:
            c.needs_user_check = True
            c.confidence = min(c.confidence, 0.5)

        # 4) trade_concession без условности → проверить
        if c.type == "trade_concession" and not any(w in low for w in _CONDITIONAL):
            c.needs_user_check = True

        # 5) пустой evidence → флаг проверки (§2)
        if not has_evidence:
            c.needs_user_check = True

    return cards
