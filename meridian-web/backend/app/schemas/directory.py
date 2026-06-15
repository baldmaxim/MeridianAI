"""Схемы справочников и модели доступа (Этап 1 MVP)."""

from datetime import datetime
from typing import Literal

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
    customer_id: int
    name: str
    address: str | None = None
    description: str | None = None
    notes: str | None = None
    is_active: bool = True


class ProjectObjectUpdate(BaseModel):
    customer_id: int | None = None
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


# --- Department ---


class DepartmentCreate(BaseModel):
    name: str
    description: str | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class DepartmentResponse(BaseModel):
    id: int
    owner_user_id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DepartmentUserResponse(BaseModel):
    """Сотрудник в составе отдела (для GET /departments/{id}/users)."""

    membership_id: int
    user_id: int
    email: str
    display_name: str | None
    created_at: datetime


# --- ObjectAccessGrant ---


class ObjectAccessGrantCreate(BaseModel):
    grantee_type: Literal["user", "department"]
    grantee_user_id: int | None = None
    grantee_department_id: int | None = None
    access_level: Literal["view", "edit", "manage"] = "view"


class ObjectAccessGrantResponse(BaseModel):
    id: int
    object_id: int
    grantee_type: str
    grantee_user_id: int | None
    grantee_department_id: int | None
    access_level: str
    created_by_user_id: int
    created_at: datetime
    grantee_name: str | None = None

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
