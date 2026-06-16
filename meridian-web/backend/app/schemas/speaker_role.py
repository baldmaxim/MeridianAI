"""Схемы persisted-ролей спикеров встречи."""

from datetime import datetime

from pydantic import BaseModel


class SpeakerRoleOut(BaseModel):
    id: int
    meeting_id: int
    speaker_label: str
    side: str  # self | opponent | ally | third_party
    display_name: str | None = None
    assigned_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SpeakerRolePut(BaseModel):
    # принимает our|opponent|third_party|unknown и live-словарь self|ally; '' / unknown → очистка
    side: str | None = None
    display_name: str | None = None
