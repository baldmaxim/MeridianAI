"""Подсказки распознаванию (keyterms) для конкретной встречи."""

import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.directory import Customer, ProjectObject
from ...models.knowledge import GlossaryTerm
from ...models.meeting import MeetingSession
from ...services.asr_lexicon import build_keyterms, load_job_lexicon_entries
from ...services.speaker_roles import get_names_map
from ..batch.transcription_service import KEYTERMS_LIMIT, KEYTERMS_MAX_CHARS, KEYTERMS_MAX_WORDS

logger = logging.getLogger("meridian.refine")


async def _priority_terms(db: AsyncSession, meeting: MeetingSession) -> list[str]:
    """Что точно звучит на этой встрече: заказчик, объект, их глоссарий, имена участников."""
    terms: list[str] = []
    if meeting.customer_id:
        customer = await db.get(Customer, meeting.customer_id)
        if customer and customer.name:
            terms.append(customer.name)
    if meeting.object_id:
        obj = await db.get(ProjectObject, meeting.object_id)
        if obj and obj.name:
            terms.append(obj.name)
    conds = []
    if meeting.customer_id:
        conds.append(GlossaryTerm.customer_id == meeting.customer_id)
    if meeting.object_id:
        conds.append(GlossaryTerm.object_id == meeting.object_id)
    if conds:
        terms += list((await db.execute(
            select(GlossaryTerm.term)
            .where(or_(*conds), GlossaryTerm.status == "approved")
            .order_by(GlossaryTerm.id)
        )).scalars().all())
    terms += list((await get_names_map(db, meeting.id)).values())
    return terms


async def build_meeting_keyterms(db: AsyncSession, meeting: MeetingSession, user_id: int) -> list[str]:
    """Приоритетные термины встречи + словарь пользователя. Сбой словаря не роняет уточнение."""
    priority: list[str] = []
    entries: list = []
    try:
        priority = await _priority_terms(db, meeting)
        entries = await load_job_lexicon_entries(db, user_id)
    except Exception as e:
        logger.warning("meeting %s: словарь для keyterms не загружен (%s), идём с тем, что есть",
                       meeting.id, type(e).__name__)
        await db.rollback()
    return build_keyterms(
        entries, limit=KEYTERMS_LIMIT, max_chars=KEYTERMS_MAX_CHARS,
        max_words=KEYTERMS_MAX_WORDS, priority_terms=priority,
    )
