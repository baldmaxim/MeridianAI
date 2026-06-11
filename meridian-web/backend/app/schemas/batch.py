"""Pydantic schemas for batch transcription jobs."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


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


class UploadSessionRequest(BaseModel):
    filename: str
    size: Optional[int] = None


class UploadSessionResponse(BaseModel):
    file_id: int
    upload_url: str
