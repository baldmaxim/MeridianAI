"""Словарь терминов для правки распознанного текста конкретного пользователя."""

import json
import logging
from typing import Iterable, List, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.batch.term_lexicon import Lexicon, load_base_lexicon_entries
from ..models.asr_term import AsrTerm
from ..models.directory import Customer, ProjectObject
from ..models.knowledge import GlossaryTerm

logger = logging.getLogger("meridian.batch")

Entry = Tuple[str, List[str], str]


def _parse_aliases(raw: str | None) -> List[str]:
    """JSON-массив строк → непустые варианты; всё остальное (битый JSON, не список) — пусто."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [a.strip() for a in data if isinstance(a, str) and a.strip()]


def _names(rows: Iterable[str | None], source: str) -> List[Entry]:
    return [(n.strip(), [], source) for n in rows if n and n.strip()]


async def load_job_lexicon_entries(db: AsyncSession, user_id: int) -> List[Entry]:
    """Записи (термин, варианты, источник): базовый словарь + термины пользователя и общие
    + глоссарий + справочник заказчиков и объектов. Источник сохраняется — по нему
    build_keyterms задаёт приоритет."""
    entries: List[Entry] = list(load_base_lexicon_entries())

    asr_rows = (await db.execute(
        select(AsrTerm.term, AsrTerm.aliases_json)
        .where(or_(AsrTerm.owner_user_id.is_(None), AsrTerm.owner_user_id == user_id))
        .order_by(AsrTerm.id)
    )).all()
    for term, aliases_json in asr_rows:
        if term and term.strip():
            entries.append((term.strip(), _parse_aliases(aliases_json), "asr_terms"))

    glossary_rows = (await db.execute(
        select(GlossaryTerm.term, GlossaryTerm.aliases_json)
        .where(GlossaryTerm.owner_user_id == user_id, GlossaryTerm.status == "approved")
        .order_by(GlossaryTerm.id)
    )).all()
    for term, aliases_json in glossary_rows:
        if term and term.strip():
            entries.append((term.strip(), _parse_aliases(aliases_json), "glossary"))

    # Справочник общий для фирмы — без фильтра по владельцу.
    entries += _names((await db.execute(select(Customer.name).order_by(Customer.id))).scalars(), "directory")
    entries += _names((await db.execute(select(ProjectObject.name).order_by(ProjectObject.id))).scalars(), "directory")

    return entries


async def load_job_lexicon(db: AsyncSession, user_id: int) -> Lexicon:
    """Словарь пользователя для правки терминов (см. load_job_lexicon_entries)."""
    entries = await load_job_lexicon_entries(db, user_id)
    lexicon = Lexicon.from_entries(entries)
    logger.info("lexicon user %s: записей %d, форм %d", user_id, len(entries), len(lexicon.forms))
    return lexicon


# Порядок источников для подсказок распознаванию: что точно звучит на этой встрече — первым.
_KEYTERM_SOURCE_ORDER = ("directory", "asr_terms", "glossary", "base")
# ElevenLabs не принимает эти символы в keyterms.
_KEYTERM_FORBIDDEN = frozenset("<>{}[]\\")
_KEYTERM_MIN_CHARS = 3


def build_keyterms(
    entries: Iterable[Entry],
    *,
    limit: int,
    max_chars: int,
    max_words: int = 5,
    priority_terms: Iterable[str] = (),
) -> List[str]:
    """Термины словаря → список keyterms для ElevenLabs (смещение модели к нужным словам).

    Порядок: priority_terms, затем источники directory → asr_terms → glossary → base.
    Берутся только канонические термины (без вариантов написания). Отсев: короче 3 или
    длиннее max_chars символов, больше max_words слов, запрещённые символы; дубли — без учёта регистра.
    """
    ordered: List[str] = list(priority_terms)
    by_source: dict[str, List[str]] = {}
    for term, _aliases, source in entries:
        by_source.setdefault(source, []).append(term)
    extra = [s for s in by_source if s not in _KEYTERM_SOURCE_ORDER]
    for source in (*_KEYTERM_SOURCE_ORDER, *extra):
        ordered += by_source.get(source, [])

    result: List[str] = []
    seen: set[str] = set()
    for raw in ordered:
        if len(result) >= limit:
            break
        term = " ".join((raw or "").split())  # крайние пробелы и двойные пробелы внутри
        if not (_KEYTERM_MIN_CHARS <= len(term) <= max_chars):
            continue
        if len(term.split()) > max_words or any(ch in _KEYTERM_FORBIDDEN for ch in term):
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result
