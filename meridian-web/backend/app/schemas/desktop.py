"""Схемы API десктоп-приложения записи встреч."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

CaptureMode = Literal["online", "in_person"]
Channel = Literal["mic", "system", "mixed"]


class DesktopLoginRequest(BaseModel):
    # Без EmailStr: на сервере почта сравнивается как строка, неверный формат — тот же 401, что и неверный пароль.
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1000)
    device_name: str = Field(min_length=1, max_length=120)
    platform: str | None = Field(default=None, max_length=20)
    app_version: str | None = Field(default=None, max_length=40)


class DesktopUserOut(BaseModel):
    id: int
    email: str
    display_name: str | None
    role: str


class DesktopDeviceOut(BaseModel):
    id: int
    name: str
    platform: str | None
    app_version: str | None
    created_at: datetime | None
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


class DesktopLoginResponse(BaseModel):
    device_token: str
    device_id: int
    user: DesktopUserOut


class DesktopMeResponse(BaseModel):
    user: DesktopUserOut
    device: DesktopDeviceOut


class MeetingUpsertRequest(BaseModel):
    client_uuid: UUID
    title: str = Field(max_length=255)
    started_at: datetime
    ended_at: datetime | None = None
    capture_mode: CaptureMode
    customer_id: int | None = None
    object_id: int | None = None


class MeetingUpsertResponse(BaseModel):
    meeting_id: int
    created: bool


class SegmentIn(BaseModel):
    client_segment_id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=20000)
    start_time: float = Field(ge=0)
    end_time: float = Field(ge=0)
    wall_clock: datetime | None = None
    channel: Channel
    speaker_label: str | None = Field(default=None, max_length=100)


class SegmentsRequest(BaseModel):
    segments: list[SegmentIn] = Field(max_length=500)


class SegmentsResponse(BaseModel):
    created: int
    updated: int


class NoteIn(BaseModel):
    at_seconds: float = Field(ge=0)
    text: str = Field(max_length=5000)


class MeetingPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    ended_at: datetime | None = None
    # None — заметки не трогать; список (даже пустой) заменяет их целиком.
    notes: list[NoteIn] | None = Field(default=None, max_length=1000)


class MeetingPatchResponse(BaseModel):
    meeting_id: int
    title: str | None
    ended_at: datetime | None


class AudioUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=300)
    size: int = Field(ge=0)
    channel: Channel


class AudioUploadResponse(BaseModel):
    file_id: int
    # None — файл уже загружен и подтверждён, грузить повторно не нужно.
    upload_url: str | None
    status: str


class AudioConfirmResponse(BaseModel):
    file_id: int
    status: str
    size: int | None


class DesktopMeetingItem(BaseModel):
    meeting_id: int
    client_uuid: str
    title: str | None
    started_at: datetime
    finalization_status: str
    protocol_ready: bool
