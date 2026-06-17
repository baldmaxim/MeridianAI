"""Схемы segment-level коррекций диаризации (Этап 8).

side нормализуется через services.speaker_roles.to_public_side (self|opponent|None).
Пустые строки label/segment_key → None / 422.
"""

from datetime import datetime

from pydantic import BaseModel


class SpeakerSegmentCorrectionPut(BaseModel):
    original_speaker_label: str | None = None
    corrected_speaker_label: str | None = None
    side: str | None = None
    note: str | None = None


class SpeakerSegmentCorrectionsBulkPutItem(SpeakerSegmentCorrectionPut):
    segment_key: str


class SpeakerSegmentCorrectionsBulkPut(BaseModel):
    items: list[SpeakerSegmentCorrectionsBulkPutItem] = []


class SpeakerSegmentCorrectionOut(BaseModel):
    id: int
    meeting_id: int
    segment_key: str
    original_speaker_label: str | None = None
    corrected_speaker_label: str | None = None
    side: str | None = None
    note: str | None = None
    created_by_user_id: int | None = None
    updated_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
