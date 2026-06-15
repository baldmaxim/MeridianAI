"""Дедупликация кандидатов знаний (Этап 7, §17).

normalize (lower/trim/ё→е) + ключи по типу; сверка с approved knowledge и pending candidates.
"""

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.knowledge import (
    LearningCandidate, GlossaryTerm, TriggerPhrase,
    NegotiationPlaybook, CounterpartyTrait, ForbiddenPhrase,
)


def normalize(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().replace("ё", "е")).strip()


def candidate_keys(candidate_type: str, payload: dict) -> list[str]:
    p = payload or {}
    if candidate_type == "term":
        keys = [normalize(p.get("term", ""))]
        keys += [normalize(a) for a in (p.get("aliases") or [])]
        return [k for k in keys if k]
    if candidate_type == "trigger_phrase":
        k = normalize(p.get("phrase", ""))
        return [k] if k else []
    if candidate_type == "playbook":
        k = normalize(p.get("situation", "")) + "|" + normalize(p.get("recommended_phrase", ""))
        return [k] if k.strip("|") else []
    if candidate_type == "counterparty_trait":
        k = normalize(p.get("trait", ""))
        return [k] if k else []
    if candidate_type == "forbidden_phrase":
        k = normalize(p.get("phrase_or_risk", ""))
        return [k] if k else []
    return []


async def existing_keys(db: AsyncSession, owner_user_id: int, candidate_type: str) -> set[str]:
    """Ключи approved-знаний и pending-кандидатов данного типа для owner."""
    keys: set[str] = set()

    if candidate_type == "term":
        rows = (await db.execute(select(GlossaryTerm).where(
            GlossaryTerm.owner_user_id == owner_user_id, GlossaryTerm.status == "approved"))).scalars().all()
        for r in rows:
            keys.add(normalize(r.term))
            for a in (json.loads(r.aliases_json) if r.aliases_json else []):
                keys.add(normalize(a))
    elif candidate_type == "trigger_phrase":
        rows = (await db.execute(select(TriggerPhrase.phrase).where(
            TriggerPhrase.owner_user_id == owner_user_id, TriggerPhrase.status == "approved"))).scalars().all()
        keys |= {normalize(x) for x in rows}
    elif candidate_type == "playbook":
        rows = (await db.execute(select(NegotiationPlaybook).where(
            NegotiationPlaybook.owner_user_id == owner_user_id, NegotiationPlaybook.status == "approved"))).scalars().all()
        keys |= {normalize(r.situation) + "|" + normalize(r.recommended_phrase) for r in rows}
    elif candidate_type == "counterparty_trait":
        rows = (await db.execute(select(CounterpartyTrait.trait).where(
            CounterpartyTrait.owner_user_id == owner_user_id, CounterpartyTrait.status == "approved"))).scalars().all()
        keys |= {normalize(x) for x in rows}
    elif candidate_type == "forbidden_phrase":
        rows = (await db.execute(select(ForbiddenPhrase.phrase_or_risk).where(
            ForbiddenPhrase.owner_user_id == owner_user_id, ForbiddenPhrase.status == "approved"))).scalars().all()
        keys |= {normalize(x) for x in rows}

    # pending candidates того же типа
    pend = (await db.execute(select(LearningCandidate.payload_json).where(
        LearningCandidate.owner_user_id == owner_user_id,
        LearningCandidate.candidate_type == candidate_type,
        LearningCandidate.status == "pending"))).scalars().all()
    for pj in pend:
        try:
            for k in candidate_keys(candidate_type, json.loads(pj)):
                keys.add(k)
        except (ValueError, TypeError):
            pass
    return keys
