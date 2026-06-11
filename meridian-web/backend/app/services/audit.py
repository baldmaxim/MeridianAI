"""Audit log (§22): запись критичных событий в отдельной транзакции.

Своя сессия (не сессия запроса) → аудит переживает rollback запроса (например,
failed login отдаёт 401 и откатывает get_db, но запись аудита должна остаться).
Email хранится как HMAC (§22), а не в открытом виде.
"""

import hashlib
import hmac
import logging

from ..config import get_settings
from ..database import async_session
from ..models.audit import AuditLog

logger = logging.getLogger("meridian.audit")


def hmac_email(email: str | None) -> str | None:
    if not email:
        return None
    s = get_settings()
    key = (s.audit_hmac_key or s.jwt_secret).encode()
    return hmac.new(key, email.strip().lower().encode(), hashlib.sha256).hexdigest()


def client_ip(request) -> str | None:
    """Реальный IP за nginx: первый из X-Forwarded-For, иначе peer."""
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


async def audit(event_type: str, actor_user_id: int | None = None, ip: str | None = None, **details) -> None:
    try:
        async with async_session() as db:
            db.add(
                AuditLog(
                    event_type=event_type,
                    actor_user_id=actor_user_id,
                    ip=ip,
                    details=details or None,
                )
            )
            await db.commit()
    except Exception:
        logger.exception("audit write failed: %s", event_type)
