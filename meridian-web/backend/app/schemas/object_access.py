"""Схемы ручной выдачи доступа к проектам."""

from datetime import datetime

from pydantic import BaseModel, Field


class UserObjectAccessPayload(BaseModel):
    """Гранты пользователя: «все проекты», заказчики целиком и отдельные объекты."""

    all_objects: bool = False
    customer_ids: list[int] = Field(default_factory=list)
    object_ids: list[int] = Field(default_factory=list)


class ObjectAccessRequestStatus(BaseModel):
    """Ответ на заявку/решение: pending | already_granted | approved | rejected."""

    status: str


class ObjectAccessRequestOut(BaseModel):
    id: int
    user_id: int
    user_email: str
    user_display_name: str | None = None
    object_id: int
    object_name: str
    customer_name: str | None = None
    status: str
    created_at: datetime
