"""Схемы persisted-ролей спикеров встречи.

Диаризация v1 — две публичные стороны: self = «Мы», opponent = «Не мы».
Исторически side мог быть ally/third_party (legacy); новые назначения — только self/opponent.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SpeakerRoleOut(BaseModel):
    id: int
    meeting_id: int
    speaker_label: str
    # исторически self|opponent|ally|third_party; UI v1 канонизирует к self|opponent;
    # None — спикер назван без выбора стороны
    side: str | None = Field(default=None, description="self = Мы, opponent = Не мы; None — сторона не выбрана")
    display_name: str | None = None
    assigned_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SpeakerRolePut(BaseModel):
    # принимает алиасы (we/not_us/ally/third_party/customer/…); unknown/clear/'' / null → очистка
    side: str | None = Field(default=None, description="self = Мы, opponent = Не мы; '' → очистить")
    display_name: str | None = None
