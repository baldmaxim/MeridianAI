"""Pydantic schemas for batch transcription jobs."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class BatchSegment(BaseModel):
    """Реплика диаризации: спикер + таймкоды + текст (для просмотрщика транскрипта)."""
    speaker: str
    start: float
    end: float
    text: str


class BatchJobResponse(BaseModel):
    id: int
    status: str
    original_filename: str
    original_size: int
    compressed_size: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchJobDetailResponse(BatchJobResponse):
    transcription_text: Optional[str] = None
    protocol_markdown: Optional[str] = None
    protocol_json: Optional[str] = None
    segments: List[BatchSegment] = []


class UploadSessionRequest(BaseModel):
    filename: str
    size: Optional[int] = None
    # Задача 5: офлайн-дозапись «дыры» записи в встречу
    meeting_id: Optional[int] = None
    kind: Optional[str] = None  # None — обычный батч; "gap_fill" — дозапись после обрыва связи


class UploadSessionResponse(BaseModel):
    file_id: int
    upload_url: str


class ConfirmUploadRequest(BaseModel):
    meeting_id: Optional[int] = None
    kind: Optional[str] = None
