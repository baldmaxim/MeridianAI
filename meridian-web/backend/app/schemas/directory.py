"""Схемы справочников и модели доступа (Этап 1 MVP)."""

from datetime import datetime

from pydantic import BaseModel


# --- Customer ---


class CustomerCreate(BaseModel):
    name: str
    inn: str | None = None
    notes: str | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    inn: str | None = None
    notes: str | None = None


class CustomerResponse(BaseModel):
    id: int
    owner_user_id: int
    name: str
    inn: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- ProjectObject ---


class ProjectObjectCreate(BaseModel):
    customer_name: str
    name: str
    address: str | None = None
    description: str | None = None
    notes: str | None = None
    is_active: bool = True


class ProjectObjectUpdate(BaseModel):
    customer_name: str | None = None
    name: str | None = None
    address: str | None = None
    description: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class ProjectObjectResponse(BaseModel):
    id: int
    owner_user_id: int
    customer_id: int
    name: str
    address: str | None
    description: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    customer_name: str | None = None

    model_config = {"from_attributes": True}


# --- MeetingParticipant ---


class MeetingParticipantResponse(BaseModel):
    id: int
    meeting_id: int
    user_id: int
    role: str
    created_at: datetime
    email: str | None = None
    display_name: str | None = None

    model_config = {"from_attributes": True}
