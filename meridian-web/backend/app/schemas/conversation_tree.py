"""Схемы дерева общения встречи (Conversation Tree)."""

from datetime import datetime

from pydantic import BaseModel, field_validator

from ..models.meeting_conversation import TOPIC_STATUSES


class ConversationTopicRef(BaseModel):
    segment_id: str
    speaker: str
    timecode: str
    text: str


class ConversationTopicOut(BaseModel):
    id: int
    meeting_id: int
    title: str
    normalized_key: str
    status: str
    our_summary: str | None = None
    opponent_summary: str | None = None
    our_last_text: str | None = None
    opponent_last_text: str | None = None
    our_refs: list[ConversationTopicRef] = []
    opponent_refs: list[ConversationTopicRef] = []
    last_updated_at: datetime
    created_at: datetime


class ConversationTopicUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    our_summary: str | None = None
    opponent_summary: str | None = None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in TOPIC_STATUSES:
            raise ValueError(f"Недопустимый статус. Разрешено: {', '.join(TOPIC_STATUSES)}")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        if v is not None:
            v = v.strip()[:255]
            if not v:
                raise ValueError("Пустой заголовок")
        return v


class ConversationTreeOut(BaseModel):
    meeting_id: int
    tree_version: int
    topics: list[ConversationTopicOut]
