"""Shared API key loading utility."""

import logging

from sqlalchemy import select

from ..database import async_session
from ..models.api_key import ApiKey
from .encryption import decrypt_api_key

logger = logging.getLogger("ai_helper.api_keys")


async def load_api_keys() -> dict:
    """Load active API keys from database."""
    keys = {}
    async with async_session() as db:
        result = await db.execute(select(ApiKey).where(ApiKey.is_active == True))
        for key in result.scalars().all():
            try:
                keys[key.service] = decrypt_api_key(key.encrypted_key)
            except Exception:
                logger.error(f"Failed to decrypt key for {key.service}")
    return keys
