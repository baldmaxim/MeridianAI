"""Схемы page-access (доступ к страницам по роли)."""

import json

from pydantic import BaseModel, field_validator


class RolePageAccessResponse(BaseModel):
    role_name: str
    allowed_pages: list[str]

    model_config = {"from_attributes": True}

    @field_validator("allowed_pages", mode="before")
    @classmethod
    def _parse(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return v


class RolePageAccessUpdate(BaseModel):
    allowed_pages: list[str]
