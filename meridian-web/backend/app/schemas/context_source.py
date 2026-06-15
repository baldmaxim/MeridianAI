"""Схемы источников контекста встречи (Этап 8): previous meetings."""

from datetime import datetime

from pydantic import BaseModel

SOURCE_TYPES = {"previous_meeting", "document", "manual", "customer_profile", "object_profile"}


class PreviousMeetingSummaryCard(BaseModel):
    """Компактная карточка прошлой встречи (для source previous_meeting)."""
    meeting_id: int
    title: str | None = None
    micro_summary: str | None = None
    customer_id: int | None = None
    customer_name: str | None = None
    object_id: int | None = None
    object_name: str | None = None
    status: str | None = None
    finalization_status: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    tags: list[str] = []
    has_protocol: bool = False
    decisions_count: int = 0
    action_items_count: int = 0
    risks_count: int = 0
    open_questions_count: int = 0


class PreviousMeetingCandidate(PreviousMeetingSummaryCard):
    """Кандидат для добавления + признак уже добавлен."""
    already_added: bool = False


class MeetingContextSourceCreate(BaseModel):
    source_type: str = "previous_meeting"
    source_id: int | None = None
    included: bool = True
    priority: int = 100
    metadata_json: str | None = None


class MeetingContextSourceUpdate(BaseModel):
    included: bool | None = None
    priority: int | None = None
    metadata_json: str | None = None


class MeetingContextSourceOut(BaseModel):
    id: int
    meeting_id: int
    source_type: str
    source_id: int | None
    included: bool
    priority: int
    added_by_user_id: int | None
    metadata_json: str | None
    created_at: datetime
    updated_at: datetime
    # для previous_meeting — карточка источника (если доступна)
    summary: PreviousMeetingSummaryCard | None = None
    # пользователь сейчас не имеет доступа к источнику (данные не раскрываются в подсказках)
    access_lost: bool = False

    model_config = {"from_attributes": True}
