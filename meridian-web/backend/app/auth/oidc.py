"""Keycloak OIDC (§9, §12): authorization-code flow + identity linking + session bridging.

AUTH_MODE=local → endpoints inert (404). При keycloak/both — SSO активен.
Стратегия: после верификации Keycloak id_token выдаём СУЩЕСТВУЮЩИЙ локальный JWT
(create_access_token) и отдаём фронту во fragment URL (#sso_token=...) — не попадает
в логи nginx. Frontend/WS-аутентификация не меняются, откат тривиален (AUTH_MODE=local).
"""

import logging
import secrets
import urllib.parse

import httpx
import jwt as pyjwt
from jwt import PyJWKClient
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models.user import User
from ..models.settings import UserSettings
from ..models.user_identity import UserIdentity
from ..services.audit import audit, hmac_email, client_ip
from .service import create_access_token

logger = logging.getLogger("meridian.oidc")
router = APIRouter()

STATE_COOKIE = "oidc_state"
_discovery: dict | None = None
_jwks_client: PyJWKClient | None = None


async def _discovery_doc() -> dict:
    global _discovery
    if _discovery is None:
        s = get_settings()
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{s.oidc_issuer}/.well-known/openid-configuration")
            r.raise_for_status()
            _discovery = r.json()
    return _discovery


def _jwks(jwks_uri: str) -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(jwks_uri)
    return _jwks_client


def _require_oidc():
    s = get_settings()
    if not s.oidc_enabled:
        raise HTTPException(status_code=404, detail="OIDC не настроен")
    return s


@router.get("/config")
async def auth_config():
    """Публичный конфиг для фронта: показывать ли кнопку SSO."""
    s = get_settings()
    return {"auth_mode": s.auth_mode, "oidc_enabled": s.oidc_enabled}


@router.get("/oidc/login")
async def oidc_login():
    s = _require_oidc()
    disc = await _discovery_doc()
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": s.oidc_client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": s.oidc_redirect_uri,
        "state": state,
    }
    url = disc["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)
    resp = RedirectResponse(url)
    resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, secure=True, samesite="lax")
    return resp


@router.get("/oidc/callback")
async def oidc_callback(
    request: Request,
    code: str = "",
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    s = _require_oidc()
    cookie_state = request.cookies.get(STATE_COOKIE)
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise HTTPException(status_code=400, detail="Invalid state")

    disc = await _discovery_doc()
    async with httpx.AsyncClient(timeout=10) as c:
        tok = await c.post(
            disc["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": s.oidc_redirect_uri,
                "client_id": s.oidc_client_id,
                "client_secret": s.oidc_client_secret,
            },
        )
    if tok.status_code != 200:
        logger.warning("OIDC token exchange failed: %s", tok.status_code)
        raise HTTPException(status_code=401, detail="OIDC token exchange failed")
    id_token = tok.json().get("id_token")
    if not id_token:
        raise HTTPException(status_code=401, detail="no id_token")

    try:
        signing_key = _jwks(disc["jwks_uri"]).get_signing_key_from_jwt(id_token)
        claims = pyjwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=s.oidc_client_id,
            issuer=s.oidc_issuer,
        )
    except Exception as e:
        logger.warning("OIDC id_token verify failed: %s", e)
        raise HTTPException(status_code=401, detail="invalid id_token")

    sub = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()
    email_verified = bool(claims.get("email_verified", False))
    roles = ((claims.get("resource_access", {}) or {}).get(s.oidc_client_id, {}) or {}).get("roles", [])

    user = await _link_or_create_user(db, sub, email, email_verified, roles)
    await db.commit()

    token = create_access_token(user.id, user.role)
    await audit("sso_login", actor_user_id=user.id, ip=client_ip(request), email_hmac=hmac_email(email))

    front = s.frontend_url or (s.cors_origins[0] if s.cors_origins else "")
    resp = RedirectResponse(f"{front}/#sso_token={token}")
    resp.delete_cookie(STATE_COOKIE)
    return resp


async def _link_or_create_user(db, sub, email, email_verified, roles) -> User:
    # 1) по (provider, subject)
    ident = (
        await db.execute(
            select(UserIdentity).where(
                UserIdentity.provider == "keycloak", UserIdentity.subject == sub
            )
        )
    ).scalar_one_or_none()
    if ident:
        user = await db.get(User, ident.user_id)
        if user:
            return user

    # 2) по верифицированному email — линкуем, локальную роль НЕ трогаем (§12)
    if email and email_verified:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user:
            db.add(UserIdentity(user_id=user.id, provider="keycloak", subject=sub, email_at_link=email))
            return user

    # 3) создать нового; роль из Keycloak ТОЛЬКО при создании
    role = "admin" if "admin" in roles else "user"
    user = User(
        email=email or f"{sub}@keycloak.local",
        password_hash="!",  # локальный логин невозможен (не bcrypt-хэш)
        role=role,
        display_name=email or sub,
    )
    db.add(user)
    await db.flush()
    db.add(UserSettings(user_id=user.id))
    db.add(UserIdentity(user_id=user.id, provider="keycloak", subject=sub, email_at_link=email))
    return user
