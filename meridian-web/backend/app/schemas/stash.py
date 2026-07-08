"""Pydantic-схемы мини-облака (обмен файлами между устройствами)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class StashUploadSessionRequest(BaseModel):
    filename: str
    size: Optional[int] = None


class StashUploadSessionResponse(BaseModel):
    file_id: int
    upload_url: str


class StashFileResponse(BaseModel):
    id: int
    original_name: str
    size: Optional[int] = None
    mime: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class StashDownloadUrlResponse(BaseModel):
    url: str


class StashDownloadItem(BaseModel):
    id: int
    original_name: str
    url: str
