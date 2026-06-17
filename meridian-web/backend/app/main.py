"""FastAPI application entry point."""

import asyncio
import logging
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text

from .config import get_settings
from .database import engine
from .logging_setup import setup_logging, request_id_var
from .ratelimit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from .auth.router import router as auth_router
from .auth.oidc import router as oidc_router
from .api.admin import router as admin_router
from .api.settings import router as settings_router, providers_router
from .api.documents import router as documents_router
from .api.meetings import router as meetings_router
from .api.roles import router as roles_router
from .api.history import router as history_router
from .api.batch import router as batch_router
from .api.customers import router as customers_router
from .api.objects import router as objects_router
from .api.mobile import router as mobile_router
from .api.learning import router as learning_router
from .api.knowledge import router as knowledge_router
from .api.context_sources import router as context_sources_router
from .api.conversation_tree import router as conversation_tree_router
from .api.speaker_roles import router as speaker_roles_router
from .api.ai_settings import router as ai_settings_router, meeting_router as ai_settings_meeting_router
from .api.role_page_access import router as page_access_router
from .api.health import router as health_api_router
from .ws.handler import router as ws_router

settings = get_settings()
setup_logging(dev_mode=settings.dev_mode)
logger = logging.getLogger("meridian")


# --- Sentry (опционально, §20) ---
def _sentry_scrub(event, hint):
    """Удалить из событий Sentry заголовки/куки/query/тела с возможными секретами."""
    req = event.get("request")
    if isinstance(req, dict):
        req.pop("cookies", None)
        req.pop("data", None)
        if "query_string" in req:
            req["query_string"] = ""
        headers = req.get("headers")
        if isinstance(headers, dict):
            for h in list(headers):
                if h.lower() in ("authorization", "cookie"):
                    headers[h] = "***"
    return event


if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        send_default_pii=False,
        before_send=_sentry_scrub,
    )
    logger.info("Sentry enabled (env=%s)", settings.environment)


def _redact_db_url(url: str) -> str:
    """Скрыть пароль в DB URL перед логированием (§20: no secrets in logs)."""
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)


def run_startup_checks() -> None:
    """§25: в проде отказываемся стартовать при небезопасной конфигурации."""
    problems = []
    if settings.jwt_secret == "change-me-in-production":
        problems.append("JWT_SECRET — небезопасный дефолт")
    if not settings.encryption_key:
        problems.append("ENCRYPTION_KEY пуст — шифрование API-ключей не работает")
    if "sqlite" in settings.database_url:
        problems.append("DATABASE_URL указывает на sqlite (§7: только PostgreSQL)")
    if not settings.database_url:
        problems.append("DATABASE_URL не задан")
    if settings.auth_mode not in ("local", "keycloak", "both"):
        problems.append(f"AUTH_MODE невалиден: {settings.auth_mode}")
    if settings.auth_mode in ("keycloak", "both") and not settings.oidc_enabled:
        problems.append("AUTH_MODE требует OIDC, но OIDC_ISSUER/CLIENT_ID/SECRET не заданы")

    # Необязательные сервисы: предупреждаем (health покажет configured=false), но не падаем
    advisories = []
    if not settings.s3_enabled:
        advisories.append("S3 не настроен — загрузка документов/аудио недоступна")
    if settings.document_max_upload_mb <= 0 or settings.document_max_upload_mb > 1024:
        advisories.append(f"DOCUMENT_MAX_UPLOAD_MB вне разумных пределов: {settings.document_max_upload_mb}")
    if settings.job_max_attempts <= 0 or settings.job_max_attempts > 20:
        advisories.append(f"JOB_MAX_ATTEMPTS вне разумных пределов: {settings.job_max_attempts}")
    for a in advisories:
        logger.warning("config advisory: %s", a)

    if not problems:
        return
    if settings.dev_mode:
        for p in problems:
            logger.warning("startup check: %s", p)
    else:
        for p in problems:
            logger.error("startup check FAILED: %s", p)
        raise RuntimeError("Небезопасная конфигурация для прода: " + "; ".join(problems))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Meridian API...")
    logger.info("Database: %s", _redact_db_url(settings.database_url))
    logger.info("DEV_MODE: %s", settings.dev_mode)

    run_startup_checks()

    # Create upload directories
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.transcription_dir, exist_ok=True)
    os.makedirs(os.path.join(settings.upload_dir, "batch"), exist_ok=True)

    # Схема БД управляется ТОЛЬКО миграциями Alembic (§8): `alembic upgrade head`
    # отдельным шагом до старта приложения. Никаких create_all/ALTER из рантайма.

    async def _session_cleanup_loop():
        while True:
            await asyncio.sleep(600)
            from .services.session_manager import cleanup_idle_sessions
            n = cleanup_idle_sessions(settings.session_idle_ttl)
            if n:
                logger.info("[Cleanup] Removed %d idle session(s)", n)

    cleanup_task = asyncio.create_task(_session_cleanup_loop())

    yield

    cleanup_task.cancel()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Meridian API",
    description="Meridian — AI-assisted negotiation helper for construction industry",
    version="1.0.0",
    lifespan=lifespan,
)

# rate limit (§5)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Назначает request_id и пишет один редактированный access-лог (без query)."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        tok = request_id_var.set(rid)
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            dur = round((time.monotonic() - start) * 1000, 1)
            # path без query → не утекает ?token=
            logger.exception(
                "request error",
                extra={"method": request.method, "path": request.url.path, "duration_ms": dur},
            )
            request_id_var.reset(tok)
            raise
        dur = round((time.monotonic() - start) * 1000, 1)
        response.headers["X-Request-ID"] = rid
        logger.info(
            "access",
            extra={
                "event": "access",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": dur,
            },
        )
        request_id_var.reset(tok)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Базовые security-заголовки (§23). HSTS/CSP — на nginx (фаза 3)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response


# Order matters: add_middleware uses LIFO — last added = outermost.
# CORS должен быть самым внешним, чтобы обрабатывать OPTIONS preflight раньше всего.
app.add_middleware(RequestContextMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


# Routes
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(oidc_router, prefix="/api/auth", tags=["auth-oidc"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(page_access_router, prefix="/api/admin/page-access", tags=["page-access"])
app.include_router(providers_router, prefix="/api/settings/providers", tags=["settings"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(documents_router, prefix="/api/documents", tags=["documents"])
app.include_router(meetings_router, prefix="/api/transcriptions", tags=["meetings"])
app.include_router(roles_router, prefix="/api/roles", tags=["roles"])
app.include_router(history_router, prefix="/api/meetings", tags=["meetings-history"])
app.include_router(batch_router, prefix="/api/batch", tags=["batch"])
# §12: page-access enforcement применяется per-endpoint в самих роутерах (require_page),
# только на МУТАЦИИ — GET-списки справочников нужны общим потокам (модалка объекта,
# фильтр истории, AI-настройки встречи), поэтому остаются открытыми.
app.include_router(customers_router, prefix="/api/customers", tags=["customers"])
app.include_router(objects_router, prefix="/api/objects", tags=["objects"])
app.include_router(mobile_router, prefix="/api/mobile", tags=["mobile"])
app.include_router(learning_router, prefix="/api", tags=["learning"])
app.include_router(knowledge_router, prefix="/api/knowledge", tags=["knowledge"])
app.include_router(context_sources_router, prefix="/api/meetings", tags=["context-sources"])
app.include_router(conversation_tree_router, prefix="/api/meetings", tags=["conversation-tree"])
app.include_router(speaker_roles_router, prefix="/api/meetings", tags=["speaker-roles"])
app.include_router(ai_settings_router, prefix="/api/ai-settings", tags=["ai-settings"])
app.include_router(ai_settings_meeting_router, prefix="/api/meetings", tags=["ai-settings"])
app.include_router(health_api_router, prefix="/api/health", tags=["health"])
app.include_router(ws_router)


@app.get("/health/live")
async def health_live():
    """Liveness: процесс жив (§5)."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    """Readiness: доступна БД (§5)."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        logger.warning("readiness check failed: %s", e)
        return JSONResponse({"status": "not ready"}, status_code=503)


# /api/health* обслуживается health_api_router (Этап 10): rich status + /deep + /jobs + /config-summary
