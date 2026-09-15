"""Парсинг/коэрция/safety-проверки структурированных подсказок (Этап 6)."""

import json
import logging
import re

from ..config import get_settings
from ..schemas.suggestion import SuggestionCard, SuggestionResponse

logger = logging.getLogger("meridian.suggestions")

_CATEGORICAL = ("обязан", "по договору", "согласно договор", "по закону", "по контракт", "по закон")
_CONDITIONAL = ("если", "при услови", "в обмен", "взамен", "одновременно фиксир", "при этом фиксир")

# Номер пункта договора: 5.1, 13.2.1, 20.7.1.13. Даты (01.09.2025) не подходят.
_CLAUSE_RE = re.compile(r"(?<![\d.])\d{1,2}(?:\.\d{1,3}){1,4}(?!\d)(?!\.\d)")
_WORD_RE = re.compile(r"[a-zа-я0-9]+")
_ELLIPSIS_RE = re.compile(r"\.\.\.|…")
_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
# Цитата считается взятой из документа, если хотя бы такая доля её трёхсловных
# кусков стоит в документе дословно (по основам слов). Пересказ близко к тексту проходит,
# пересказ «по мотивам» и додуманный текст — нет.
_QUOTE_GROUNDING_MIN = 0.2
# Модель сокращает цитату («ГП выполнил доп. работы») — без разворота верный пересказ
# выглядел бы выдумкой. Разворачиваем одинаково в цитате и в документе.
_ABBREVIATIONS = {
    "гп": "генеральный подрядчик", "генподрядчик": "генеральный подрядчик",
    "доп": "дополнительный", "допник": "дополнительное соглашение",
    "дс": "дополнительное соглашение", "рд": "рабочая документация",
    "техзаказчик": "технический заказчик", "ид": "исполнительная документация",
}
_GROUNDED_CONFIDENCE_CAP = 0.6


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


def _stem_words(text: str) -> list[str]:
    stems = []
    for word in _WORD_RE.findall((text or "").lower().replace("ё", "е")):
        stems += [w[:5] for w in _ABBREVIATIONS.get(word, word).split()]
    return stems


def _shingles(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def _clause_in_context(clause: str, ctx: str) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(clause)}(?!\d)", ctx) is not None


def quote_grounding(quote: str, ctx_shingles: set[tuple[str, ...]]) -> float | None:
    """Доля трёхсловных кусков цитаты, дословно найденных в документе. None — цитата
    слишком короткая, чтобы судить. Номера пунктов не считаем: их сверяет отдельная проверка."""
    pieces = _ELLIPSIS_RE.split(_CLAUSE_RE.sub(" ", _BRACKET_RE.sub(" ", quote or "")))
    shingles: set[tuple[str, ...]] = set()
    for piece in pieces:
        shingles |= _shingles(_stem_words(piece))
    if len(shingles) < 2:
        return None
    return len(shingles & ctx_shingles) / len(shingles)


def ungrounded_reasons(card: SuggestionCard, doc_context_text: str) -> list[str]:
    """Что в карточке не подтверждается текстом документов, переданных модели.

    Модель уверенно цитирует договор, но может сослаться на пункт, которого нет, или
    дописать обрывок страницы своими словами («[подлежат возврату]») — и поставить
    needs_user_check=false. Сверяем с тем, что она реально видела.
    """
    ctx = doc_context_text or ""
    doc_quotes = [e.text or "" for e in card.evidence if e.source == "document"]
    reasons = []
    cited = set(_CLAUSE_RE.findall(card.text or ""))
    for quote in doc_quotes:
        cited |= set(_CLAUSE_RE.findall(quote))
    missing = sorted(c for c in cited if not _clause_in_context(c, ctx))
    if missing:
        reasons.append("пункт не найден в документах: " + ", ".join(missing))
    if not doc_quotes or not ctx:
        return reasons
    ctx_low = ctx.lower()
    ctx_shingles = _shingles(_stem_words(ctx))
    for quote in doc_quotes:
        guessed = [b for b in _BRACKET_RE.findall(quote) if b.strip().lower() not in ctx_low]
        if guessed:
            reasons.append("цитата дописана моделью: [" + "], [".join(guessed) + "]")
        share = quote_grounding(quote, ctx_shingles)
        if share is not None and share < _QUOTE_GROUNDING_MIN:
            reasons.append(f"цитата не совпадает с текстом документа ({share:.0%})")
    return reasons


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

        # 6) номер пункта или цитата не подтверждаются текстом документов → проверить
        reasons = ungrounded_reasons(c, doc_context_text)
        if reasons:
            c.needs_user_check = True
            c.confidence = min(c.confidence, _GROUNDED_CONFIDENCE_CAP)
            logger.info("карточка «%s» требует проверки: %s", (c.title or "")[:60], "; ".join(reasons))

    return cards
