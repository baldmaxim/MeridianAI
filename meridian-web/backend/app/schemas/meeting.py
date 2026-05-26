"""Meeting schemas."""

from datetime import datetime

from pydantic import BaseModel


class MeetingContextUpdate(BaseModel):
    topic: str = ""
    notes: str = ""


class DocumentResponse(BaseModel):
    filename: str
    doc_type: str
    doc_type_label: str
    page_count: int


class MeetingDocumentResponse(BaseModel):
    filename: str
    doc_type: str
    doc_type_label: str
    page_count: int

    model_config = {"from_attributes": True}


class SaveTranscriptionRequest(BaseModel):
    filename: str
    format: str = "txt"  # txt | json


class TranscriptionResponse(BaseModel):
    id: int
    filename: str
    format: str
    segment_count: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Meeting history ---


class MeetingListItem(BaseModel):
    id: int
    title: str | None
    meeting_topic: str | None
    negotiation_type: str | None
    started_at: datetime
    ended_at: datetime | None
    segment_count: int
    suggestion_count: int

    model_config = {"from_attributes": True}


class TranscriptSegmentResponse(BaseModel):
    segment_id: str
    text: str
    speaker_id: str
    speaker_label: str | None
    start_time: float
    end_time: float
    wall_clock: datetime
    origin: str

    model_config = {"from_attributes": True}


class MeetingSuggestionResponse(BaseModel):
    id: int
    text: str
    is_auto: bool
    suggestion_type: str | None
    trigger: str | None
    confidence: int | None
    context_info: str | None
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MeetingDetailResponse(BaseModel):
    id: int
    title: str | None
    meeting_topic: str | None
    meeting_notes: str | None
    negotiation_type: str | None
    meeting_role: str | None
    opponent_weaknesses: str | None
    started_at: datetime
    ended_at: datetime | None
    segments: list[TranscriptSegmentResponse]
    suggestions: list[MeetingSuggestionResponse]
    documents: list[MeetingDocumentResponse] = []

    model_config = {"from_attributes": True}


class MeetingTitleUpdate(BaseModel):
    title: str


class MeetingBatchDelete(BaseModel):
    ids: list[int]
