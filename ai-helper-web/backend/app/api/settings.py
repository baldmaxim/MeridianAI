"""User settings API routes."""

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.settings import UserSettings
from ..models.api_key import ApiKey
from ..schemas.settings import UserSettingsResponse, UserSettingsUpdate
from ..auth.dependencies import get_current_user

router = APIRouter()
providers_router = APIRouter()


async def _get_or_create_settings(
    user_id: int, db: AsyncSession
) -> UserSettings:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        await db.flush()
    return settings


@providers_router.get("")
async def get_active_providers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == "admin":
        result = await db.execute(select(ApiKey.service).distinct())
    else:
        result = await db.execute(
            select(ApiKey.service).where(ApiKey.is_active == True).distinct()
        )
    services = [row[0] for row in result.all()]
    return {"active_services": services}


@router.get("", response_model=UserSettingsResponse)
async def get_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = await _get_or_create_settings(user.id, db)
    return settings


@router.put("", response_model=UserSettingsResponse)
async def update_settings(
    data: UserSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = await _get_or_create_settings(user.id, db)

    update_data = data.model_dump(exclude_unset=True)
    for field in ("custom_suggestion_types", "custom_trigger_keywords"):
        if field in update_data and update_data[field] is not None:
            update_data[field] = json.dumps(
                update_data[field], ensure_ascii=False
            )
    for field, value in update_data.items():
        setattr(settings, field, value)

    return settings
