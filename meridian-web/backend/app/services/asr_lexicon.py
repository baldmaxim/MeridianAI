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


async def load_job_lexicon(db: AsyncSession, user_id: int) -> Lexicon:
    """Базовый словарь + термины пользователя и общие + глоссарий + справочник заказчиков и объектов."""
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

    lexicon = Lexicon.from_entries(entries)
    logger.info("lexicon user %s: записей %d, форм %d", user_id, len(entries), len(lexicon.forms))
    return lexicon
