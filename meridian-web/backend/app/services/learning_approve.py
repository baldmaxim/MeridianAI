"""Применение approved-кандидата → элемент базы знаний (Этап 7).

Только при ручном approve. Создаёт knowledge-элемент из payload кандидата,
проставляет created_from_candidate_id/meeting_id и помечает кандидата approved.
"""

import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.knowledge import (
    LearningCandidate, GlossaryTerm, TriggerPhrase,
    NegotiationPlaybook, CounterpartyTrait, ForbiddenPhrase,
)


def _resolve_scope(scope: str, cand: LearningCandidate) -> tuple[int | None, int | None]:
    """(customer_id, object_id) для knowledge-элемента по scope + привязкам кандидата."""
    if scope == "object" and cand.object_id:
        return cand.customer_id, cand.object_id
    if scope in ("object", "customer") and cand.customer_id:
        return cand.customer_id, None
    return None, None


def _dumps(v) -> str | None:
    return json.dumps(v, ensure_ascii=False) if v else None


def build_knowledge_item(cand: LearningCandidate):
    """Создать (не добавляя в сессию) ORM-объект знания из кандидата. None если тип неизвестен."""
    payload = json.loads(cand.payload_json) if cand.payload_json else {}
    scope = payload.get("scope") or ("customer" if cand.candidate_type == "counterparty_trait" else "global")
    cust, obj = _resolve_scope(scope, cand)
    common = dict(
        owner_user_id=cand.owner_user_id, customer_id=cust, object_id=obj, scope=scope,
        status="approved", created_from_candidate_id=cand.id, created_from_meeting_id=cand.meeting_id,
    )
    t = cand.candidate_type
    if t == "term":
        return GlossaryTerm(term=payload.get("term", "")[:300], definition=payload.get("definition", ""),
                            aliases_json=_dumps(payload.get("aliases")), **common)
    if t == "trigger_phrase":
        return TriggerPhrase(phrase=payload.get("phrase", "")[:500],
                             event_type=payload.get("event_type", "other"),
                             recommended_reaction=payload.get("recommended_reaction", ""), **common)
    if t == "playbook":
        return NegotiationPlaybook(situation=payload.get("situation", ""),
                                   recommended_phrase=payload.get("recommended_phrase", ""),
                                   technique=payload.get("technique", "other"),
                                   ask_in_return_json=_dumps(payload.get("ask_in_return")),
                                   risks_json=_dumps(payload.get("risks")), **common)
    if t == "counterparty_trait":
        # trait scope только customer|object
        if scope == "global":
            common["scope"] = "customer"
        return CounterpartyTrait(trait=payload.get("trait", ""), evidence=payload.get("evidence"),
                                 recommended_strategy=payload.get("recommended_strategy"),
                                 confidence=cand.confidence, **common)
    if t == "forbidden_phrase":
        return ForbiddenPhrase(phrase_or_risk=payload.get("phrase_or_risk", ""),
                               better_alternative=payload.get("better_alternative"),
                               reason=payload.get("reason"), **common)
    return None


async def approve_candidate(db: AsyncSession, cand: LearningCandidate, user_id: int):
    """Применить кандидата: создать knowledge-элемент, пометить approved. Коммитит вызывающий."""
    item = build_knowledge_item(cand)
    if item is None:
        return None
    db.add(item)
    cand.status = "approved"
    cand.reviewed_by_user_id = user_id
    cand.reviewed_at = datetime.utcnow()
    return item
