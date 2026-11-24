# -*- coding: utf-8 -*-
"""Структурный протокол встречи: решения, поручения, риски, открытые вопросы."""

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.protocol import MeetingActionItem, MeetingDecision, MeetingOpenQuestion, MeetingRisk
from ..schemas.finalization import (
    ProtocolActionItemOut,
    ProtocolDecisionOut,
    ProtocolOpenQuestionOut,
    ProtocolRiskOut,
)


def parse_evidence(s: str | None) -> list:
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


@dataclass
class ProtocolLists:
    decisions: list[ProtocolDecisionOut]
    action_items: list[ProtocolActionItemOut]
    risks: list[ProtocolRiskOut]
    open_questions: list[ProtocolOpenQuestionOut]


async def load_protocol_lists(db: AsyncSession, meeting_id: int) -> ProtocolLists:
    decisions = (await db.execute(select(MeetingDecision).where(MeetingDecision.meeting_id == meeting_id).order_by(MeetingDecision.id))).scalars().all()
    actions = (await db.execute(select(MeetingActionItem).where(MeetingActionItem.meeting_id == meeting_id).order_by(MeetingActionItem.id))).scalars().all()
    risks = (await db.execute(select(MeetingRisk).where(MeetingRisk.meeting_id == meeting_id).order_by(MeetingRisk.id))).scalars().all()
    questions = (await db.execute(select(MeetingOpenQuestion).where(MeetingOpenQuestion.meeting_id == meeting_id).order_by(MeetingOpenQuestion.id))).scalars().all()
    return ProtocolLists(
        decisions=[ProtocolDecisionOut(id=d.id, text=d.text, status=d.status, evidence=parse_evidence(d.evidence_json), created_at=d.created_at) for d in decisions],
        action_items=[ProtocolActionItemOut(id=a.id, task=a.task, owner_text=a.owner_text, due_text=a.due_text, status=a.status, evidence=parse_evidence(a.evidence_json), created_at=a.created_at) for a in actions],
        risks=[ProtocolRiskOut(id=r.id, text=r.text, severity=r.severity, evidence=parse_evidence(r.evidence_json), created_at=r.created_at) for r in risks],
        open_questions=[ProtocolOpenQuestionOut(id=q.id, text=q.text, evidence=parse_evidence(q.evidence_json), created_at=q.created_at) for q in questions],
    )
