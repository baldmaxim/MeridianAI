"""Автоклассификация документа: тип и теги из закрытых списков + реквизиты.

Сначала дешёвые правила (regex по имени файла, листам и началу текста). Если тип однозначно
не определился и есть ключ OpenRouter — один короткий вызов LLM. Любой сбой LLM не критичен:
остаётся результат правил или тип «other».

В мету кладём только реквизиты (ИНН/БИН, номер, дата, сумма, контрагент), а не текст документа.
В логи текст документа не попадает.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..core.llm.client import LLMClient
from ..models.directory import Customer
from .api_keys import load_api_keys
from .suggestion_parser import extract_json_from_text

logger = logging.getLogger("meridian.documents")

# --- закрытые списки (ключи — английские, подписи — для API/интерфейса) ---

DOC_TYPE_LABELS: dict[str, str] = {
    "letter": "Письмо",
    "offer": "Оферта / КП",
    "contract": "Договор",
    "supplement": "Допсоглашение",
    "bor": "ВОР",
    "estimate": "Смета",
    "specification": "Спецификация",
    "act": "Акт",
    "protocol": "Протокол",
    "other": "Прочее",
}
DOC_TYPES: tuple[str, ...] = tuple(DOC_TYPE_LABELS)

DOC_TAG_LABELS: dict[str, str] = {
    "price": "Цена",
    "deadline": "Сроки",
    "payment": "Оплата / аванс",
    "penalty": "Неустойка / штрафы",
    "warranty": "Гарантия",
    "scope": "Объёмы работ",
    "claim": "Претензия",
    "extra_work": "Доп. работы",
}
DOC_TAGS: tuple[str, ...] = tuple(DOC_TAG_LABELS)

SOURCE_RULES = "rules"
SOURCE_LLM = "llm"

# Сколько текста смотрим: тип — по началу (шапка документа), теги — глубже.
TYPE_HEAD_CHARS = 2000
TAGS_HEAD_CHARS = 20000
LLM_TEXT_CHARS = 4000
LLM_MAX_TOKENS = 300
LLM_TIMEOUT_SECONDS = 45
MAX_INN = 5

_FLAGS = re.IGNORECASE

# Порядок не важен: тип считается подходящим, если сработало хотя бы одно правило.
_TYPE_RULES: dict[str, re.Pattern[str]] = {
    "supplement": re.compile(r"дополнительное\s+соглашение|доп\.?\s*соглаш", _FLAGS),
    "contract": re.compile(r"договор\s*(?:подряда|поставки|№|n)", _FLAGS),
    "bor": re.compile(r"ведомость\s+объ[её]мов|\bвор\b", _FLAGS),
    "estimate": re.compile(r"локальн\w*\s+смет|сметный\s+расч|\bсмета\b", _FLAGS),
    "offer": re.compile(r"коммерческое\s+предложение|\bкп\b|оферт", _FLAGS),
    "specification": re.compile(r"спецификац", _FLAGS),
    "act": re.compile(r"\bакт\b|кс-2|кс-3", _FLAGS),
    "protocol": re.compile(r"протокол", _FLAGS),
    "letter": re.compile(r"исх\.?\s*№|уважаем\w+", _FLAGS),
}

_TAG_RULES: dict[str, re.Pattern[str]] = {
    "penalty": re.compile(r"неустойк|штраф|\bпен[ия]\b", _FLAGS),
    "payment": re.compile(r"аванс|оплат", _FLAGS),
    "warranty": re.compile(r"гарант", _FLAGS),
    "deadline": re.compile(r"срок", _FLAGS),
    "price": re.compile(r"стоимост|\bцен[аыу]\b|\bруб|тенге|₸", _FLAGS),
    "claim": re.compile(r"претензи", _FLAGS),
    "extra_work": re.compile(r"дополнительн\w+\s+работ", _FLAGS),
    "scope": re.compile(r"объ[её]м", _FLAGS),
}

_INN_RE = re.compile(r"(?:ИНН|БИН)\s*[:№]?\s*(\d{10}|\d{12})(?!\d)", _FLAGS)
_NUMBER_RE = re.compile(r"№\s*([\w\-/]+)")
_DATE_RE = re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{4})(?!\d)")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_AMOUNT_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*(руб|₽|тенге|тг\b|₸|kzt)",
    _FLAGS,
)
_CURRENCY = {"руб": "RUB", "₽": "RUB", "тенге": "KZT", "тг": "KZT", "₸": "KZT", "kzt": "KZT"}


@dataclass
class ClassifyResult:
    doc_type: str
    tags: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    source: str = SOURCE_RULES


# --- представление для API ---


def type_label(doc_type: str | None) -> str | None:
    return DOC_TYPE_LABELS.get(doc_type) if doc_type else None


def tag_items(tags: list[str] | None) -> list[dict[str, str]]:
    """Теги в виде {key,label}; ключи вне закрытого списка (устаревшие) пропускаются."""
    return [{"key": t, "label": DOC_TAG_LABELS[t]} for t in (tags or []) if t in DOC_TAG_LABELS]


def vocab() -> dict[str, list[dict[str, str]]]:
    return {
        "doc_types": [{"key": k, "label": v} for k, v in DOC_TYPE_LABELS.items()],
        "doc_tags": [{"key": k, "label": v} for k, v in DOC_TAG_LABELS.items()],
    }


# --- правила ---


def _match_types(filename: str, head_text: str, sheet_names: list[str] | None) -> list[str]:
    haystack = " ".join(
        [filename or "", " ".join(sheet_names or []), (head_text or "")[:TYPE_HEAD_CHARS]]
    ).lower()
    matched = {t for t, rx in _TYPE_RULES.items() if rx.search(haystack)}
    if "supplement" in matched:
        matched.discard("contract")  # текст допсоглашения всегда ссылается на договор
    return sorted(matched)


def extract_tags(text: str) -> list[str]:
    head = (text or "")[:TAGS_HEAD_CHARS]
    return [tag for tag, rx in _TAG_RULES.items() if rx.search(head)]


def _valid_date(day: int, month: int, year: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_amount(raw: str) -> float | None:
    try:
        return float(re.sub(r"[  ]", "", raw).replace(",", "."))
    except ValueError:
        return None


def extract_meta(text: str) -> dict:
    """Реквизиты из начала документа. Полный текст в мету не попадает."""
    head = text or ""
    meta: dict = {}

    inns: list[str] = []
    for m in _INN_RE.finditer(head):
        if m.group(1) not in inns:
            inns.append(m.group(1))
        if len(inns) >= MAX_INN:
            break
    if inns:
        meta["inn"] = inns

    m = _NUMBER_RE.search(head[:TYPE_HEAD_CHARS])
    if m:
        number = m.group(1).strip("-/_")[:50]
        if number:
            meta["number"] = number

    for m in _DATE_RE.finditer(head[:TYPE_HEAD_CHARS]):
        iso = _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            meta["date"] = iso
            break

    best: tuple[float, str] | None = None
    for m in _AMOUNT_RE.finditer(head):
        value = _parse_amount(m.group(1))
        if value is not None and (best is None or value > best[0]):
            best = (value, _CURRENCY[m.group(2).lower()])
    if best:
        meta["amount"] = f"{best[0]:.2f} {best[1]}"
    return meta


def classify_by_rules(
    filename: str, head_text: str, sheet_names: list[str] | None = None,
) -> ClassifyResult | None:
    """Уверенный результат правил или None, если тип не определился однозначно."""
    matched = _match_types(filename, head_text, sheet_names)
    if len(matched) != 1:
        return None
    return ClassifyResult(
        doc_type=matched[0], tags=extract_tags(head_text), meta=extract_meta(head_text),
        source=SOURCE_RULES,
    )


# --- LLM ---

_LLM_SYSTEM_PROMPT = (
    "Ты классифицируешь строительные документы. Отвечай только JSON, без пояснений."
)


def _build_llm_prompt(filename: str, text: str) -> str:
    types = ", ".join(f"{k} ({v})" for k, v in DOC_TYPE_LABELS.items())
    tags = ", ".join(f"{k} ({v})" for k, v in DOC_TAG_LABELS.items())
    return (
        f"Имя файла: {filename}\n\nНачало документа:\n{text[:LLM_TEXT_CHARS]}\n\n"
        f"Определи тип документа из списка: {types}.\n"
        f"Выбери теги (0 и более) только из списка: {tags}.\n"
        "Найди контрагента (название организации, не наша сторона), номер и дату документа.\n"
        'Ответ строго JSON: {"doc_type": "...", "tags": ["..."], '
        '"counterparty_name": "...", "number": "...", "date": "ДД.ММ.ГГГГ"}. '
        "Нет данных — пустая строка."
    )


def _normalize_date(value: object) -> str | None:
    raw = str(value or "").strip()
    m = _DATE_RE.fullmatch(raw)
    if m:
        return _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _ISO_DATE_RE.match(raw)
    if m:
        return _valid_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _sanitize_llm(data: dict) -> tuple[str, list[str], dict]:
    """Тип вне списка → «other», неизвестные теги отбрасываются, мета — только короткие строки."""
    doc_type = data.get("doc_type")
    if not isinstance(doc_type, str) or doc_type not in DOC_TYPE_LABELS:
        doc_type = "other"
    raw_tags = data.get("tags")
    tags = [t for t in (raw_tags if isinstance(raw_tags, list) else [])
            if isinstance(t, str) and t in DOC_TAG_LABELS]
    meta: dict = {}
    name = str(data.get("counterparty_name") or "").strip()[:200]
    if name:
        meta["counterparty_name"] = name
    number = str(data.get("number") or "").strip()[:50]
    if number:
        meta["number"] = number
    iso = _normalize_date(data.get("date"))
    if iso:
        meta["date"] = iso
    return doc_type, list(dict.fromkeys(tags)), meta


async def _classify_by_llm(filename: str, text_head: str) -> tuple[str, list[str], dict] | None:
    """Один вызов LLM. None — ключа нет, сбой, таймаут или нечитаемый ответ."""
    api_keys = await load_api_keys()
    key = api_keys.get("openrouter")
    if not key:
        return None
    client = LLMClient(
        api_key=key, model=get_settings().learning_model, temperature=0,
        max_tokens=LLM_MAX_TOKENS, timeout=LLM_TIMEOUT_SECONDS,
    )
    client.set_system_prompt(_LLM_SYSTEM_PROMPT)
    raw = await asyncio.wait_for(
        client.get_suggestion_async(_build_llm_prompt(filename, text_head), max_tokens=LLM_MAX_TOKENS),
        timeout=LLM_TIMEOUT_SECONDS + 5,
    )
    payload = extract_json_from_text(raw)
    if not payload:
        return None
    data = json.loads(payload)
    return _sanitize_llm(data) if isinstance(data, dict) else None


def _merge_tags(*groups: list[str]) -> list[str]:
    merged = {t for g in groups for t in g}
    return [t for t in DOC_TAGS if t in merged]  # стабильный порядок по закрытому списку


async def classify_document(
    text_head: str, filename: str, sheet_names: list[str] | None = None,
) -> ClassifyResult:
    """Тип + теги + реквизиты. Не бросает исключений из-за LLM."""
    rules = classify_by_rules(filename, text_head, sheet_names)
    if rules is not None:
        return rules

    tags = extract_tags(text_head)
    meta = extract_meta(text_head)
    fallback = ClassifyResult(doc_type="other", tags=tags, meta=meta, source=SOURCE_RULES)
    try:
        llm = await _classify_by_llm(filename, text_head)
    except Exception as e:  # LLM недоступна/таймаут/мусор — это не повод ронять обработку документа
        logger.warning("classify: LLM не помогла (%s)", type(e).__name__)
        return fallback
    if llm is None:
        return fallback
    llm_type, llm_tags, llm_meta = llm
    return ClassifyResult(
        doc_type=llm_type,
        tags=_merge_tags(tags, llm_tags),
        meta={**llm_meta, **meta},  # реквизиты, найденные regex, надёжнее ответа модели
        source=SOURCE_LLM,
    )


async def match_customer_by_inn(db: AsyncSession, inns: list[str]) -> int | None:
    """id заказчика, если по ИНН/БИН из документа нашёлся ровно один заказчик, иначе None."""
    if not inns:
        return None
    ids = (
        await db.execute(select(Customer.id).where(Customer.inn.in_(inns)).distinct().limit(2))
    ).scalars().all()
    return ids[0] if len(ids) == 1 else None
