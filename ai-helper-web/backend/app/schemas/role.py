"""Role schemas."""

from datetime import datetime
from pydantic import BaseModel


class RoleCreate(BaseModel):
    name: str
    description: str = ""
    interests: str = ""
    opponents: str = ""
    custom_instructions: str = ""


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    interests: str | None = None
    opponents: str | None = None
    custom_instructions: str | None = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: str
    interests: str
    opponents: str
    custom_instructions: str
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}
