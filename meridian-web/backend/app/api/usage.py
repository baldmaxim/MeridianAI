"""Остаток кредитов ElevenLabs и баланс OpenRouter (только админ) для индикаторов в шапке. Mounted at /api/usage."""

import logging
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..auth.dependencies import get_current_user, require_admin
from ..config import get_settings
from ..models.user import User
from ..services.api_keys import load_api_keys

logger = logging.getLogger("meridian.usage")

router = APIRouter()

_SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"
_OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"
_OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
_TIMEOUT_SEC = 10.0
_CACHE_TTL_SEC = 120.0

# (момент сохранения monotonic, ответ) — общий на процесс: ключ ElevenLabs один на всех
_cache: tuple[float, dict] | None = None
# то же для баланса OpenRouter (отдельный кэш: другой ключ и другой ответ)
_or_cache: tuple[float, dict] | None = None


def _reset_cache() -> None:
    global _cache, _or_cache
    _cache = None
    _or_cache = None


def _build_payload(data: dict) -> dict:
    used = int(data.get("character_count") or 0)
    limit = int(data.get("character_limit") or 0)
    reset_unix = data.get("next_character_count_reset_unix")
    next_reset = None
    if reset_unix:
        next_reset = datetime.fromtimestamp(int(reset_unix), tz=timezone.utc).date().isoformat()
    return {
        "used": used,
        "limit": limit,
        "remaining": limit - used,
        "percent_used": round(used * 100 / limit) if limit else 0,
        "next_reset": next_reset,
    }


async def _fetch_subscription(api_key: str, proxy: str) -> dict:
    """GET /v1/user/subscription (через прокси, если задан). Ключ в логи не попадает."""
    async with httpx.AsyncClient(proxy=proxy or None, timeout=_TIMEOUT_SEC) as client:
        resp = await client.get(_SUBSCRIPTION_URL, headers={"xi-api-key": api_key})
        resp.raise_for_status()
        return resp.json()


@router.get("/elevenlabs")
async def get_elevenlabs_usage(_: User = Depends(get_current_user)) -> dict:
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < _CACHE_TTL_SEC:
        return _cache[1]

    api_key = (await load_api_keys()).get("elevenlabs")
    if not api_key:
        raise HTTPException(status_code=404, detail="нет ключа ElevenLabs")

    try:
        data = await _fetch_subscription(api_key, get_settings().elevenlabs_proxy_url)
        payload = _build_payload(data)
    except Exception as e:
        # только тип ошибки и статус — тело/заголовки (с ключом) не логируем
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
        logger.warning("ElevenLabs subscription: %s status=%s", type(e).__name__, status)
        raise HTTPException(status_code=502, detail="ElevenLabs недоступен") from None

    _cache = (now, payload)
    return payload


def _round2(v: float) -> float:
    return round(float(v), 2)


async def _fetch_openrouter_credits(
    api_key: str, proxy: str, transport: httpx.AsyncBaseTransport | None = None
) -> dict:
    """Баланс OpenRouter → {"balance": float | None, "source": "key" | "account" | None}.

    Сначала /key: остаток по лимиту ключа (limit_remaining), source="key".
    Если у ключа нет лимита (null) — /credits: total_credits − total_usage, source="account";
    401/403 на /credits → balance=None. Через прокси, если задан. Ключ в логи не попадает.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(proxy=proxy or None, timeout=_TIMEOUT_SEC, transport=transport) as client:
        resp = await client.get(_OPENROUTER_KEY_URL, headers=headers)
        resp.raise_for_status()
        remaining = (resp.json().get("data") or {}).get("limit_remaining")
        if remaining is not None:
            return {"balance": float(remaining), "source": "key"}

        resp = await client.get(_OPENROUTER_CREDITS_URL, headers=headers)
        if resp.status_code in (401, 403):
            return {"balance": None, "source": None}
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        balance = float(data.get("total_credits") or 0) - float(data.get("total_usage") or 0)
        return {"balance": balance, "source": "account"}


def _build_openrouter_payload(raw: dict) -> dict:
    balance = raw.get("balance")
    if balance is None:
        return {"balance": None, "source": None}
    return {"balance": _round2(balance), "source": raw.get("source")}


@router.get("/openrouter")
async def get_openrouter_usage(_: User = Depends(require_admin)) -> dict:
    global _or_cache
    now = time.monotonic()
    if _or_cache and now - _or_cache[0] < _CACHE_TTL_SEC:
        return _or_cache[1]

    api_key = (await load_api_keys()).get("openrouter")
    if not api_key:
        raise HTTPException(status_code=404, detail="нет ключа OpenRouter")

    try:
        raw = await _fetch_openrouter_credits(api_key, get_settings().openrouter_proxy_url)
        payload = _build_openrouter_payload(raw)
    except Exception as e:
        # только тип ошибки и статус — тело/заголовки (с ключом) не логируем
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
        logger.warning("OpenRouter credits: %s status=%s", type(e).__name__, status)
        raise HTTPException(status_code=502, detail="OpenRouter недоступен") from None

    _or_cache = (now, payload)
    return payload
