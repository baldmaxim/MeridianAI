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
    # Русский перевод, если реплика прозвучала на другом языке. None — реплика русская
    # либо перевод не выполнялся. Оригинал в text остаётся всегда.
    text_ru: str | None = None


class BatchJobResponse(BaseModel):
    id: int
    status: str
    original_filename: str
    original_size: int
    compressed_size: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Встреча, сделанная из этой записи (если сделана) — чтобы не импортировать дважды.
    meeting_id: Optional[int] = None

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


class ClipRequest(BaseModel):
    start: float
    end: float

class BatchToMeetingRequest(BaseModel):
    """Превратить готовую запись во встречу.

    customer_id важен не для красоты: без заказчика при извлечении знаний особенности
    контрагента отбрасываются (их некуда привязать).
    """
    customer_id: Optional[int] = None
    object_id: Optional[int] = None
    title: Optional[str] = None


class BatchToMeetingResponse(BaseModel):
    meeting_id: int
    title: Optional[str] = None
    segments_added: int
    finalization_queued: bool
