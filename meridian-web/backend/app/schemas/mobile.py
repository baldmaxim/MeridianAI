"""Схемы мобильного кабинета (Этап 3)."""

from datetime import datetime

from pydantic import BaseModel

from .document import MeetingDocumentItem
from .context_source import PreviousMeetingSummaryCard
from .finalization import (
    ProtocolDecisionOut,
    ProtocolActionItemOut,
    ProtocolRiskOut,
    ProtocolOpenQuestionOut,
)


class MobileMeetingListItem(BaseModel):
    id: int
    title: str | None
    micro_summary: str | None
    status: str | None
    customer_id: int | None
    customer_name: str | None
    object_id: int | None
    object_name: str | None
    meeting_topic: str | None
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime  # = started_at (у MeetingSession нет отдельного created_at)
    created_by_user_id: int | None
    current_user_role: str
    can_record: bool
    is_live: bool
    phone_connected: bool
    desktop_connected: bool
    finalization_status: str | None = None
    tags: list[str] = []


class MobileParticipant(BaseModel):
    user_id: int
    role: str
    email: str | None
    display_name: str | None


class MobileTranscriptLine(BaseModel):
    speaker: str
    text: str
    wall_clock: datetime


class MobileMeetingDetail(BaseModel):
    id: int
    title: str | None
    status: str | None
    customer_id: int | None
    customer_name: str | None
    object_id: int | None
    object_name: str | None
    meeting_topic: str | None
    meeting_notes: str | None
    negotiation_type: str | None
    meeting_role: str | None
    opponent_weaknesses: str | None
    micro_summary: str | None
    started_at: datetime
    ended_at: datetime | None
    created_by_user_id: int | None
    participants: list[MobileParticipant]
    can_current_user_record: bool
    current_user_role: str
    live_state: dict
    recent_segments: list[MobileTranscriptLine]
    documents: list[MeetingDocumentItem] = []
    # Этап 5: финализация
    finalization_status: str | None = None
    finalization_error: str | None = None
    tags: list[str] = []
    has_protocol: bool = False
    decisions: list[ProtocolDecisionOut] = []
    action_items: list[ProtocolActionItemOut] = []
    risks: list[ProtocolRiskOut] = []
    open_questions: list[ProtocolOpenQuestionOut] = []
    # Этап 8: выбранные прошлые встречи как контекст (read-only)
    previous_context: list[PreviousMeetingSummaryCard] = []
