"""FastAPI application entry point."""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings
from .database import engine, Base
from .auth.router import router as auth_router
from .api.admin import router as admin_router
from .api.settings import router as settings_router, providers_router
from .api.documents import router as documents_router
from .api.meetings import router as meetings_router
from .api.roles import router as roles_router
from .api.history import router as history_router
from .ws.handler import router as ws_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
# Silence noisy libraries
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("watchfiles").setLevel(logging.WARNING)

logger = logging.getLogger("ai_helper")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Helper API...")
    logger.info(f"Database: {settings.database_url}")
    logger.info(f"CORS origins: localhost:3000-3009, 5170-5199, 8000-8009")

    # Create upload directories
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.transcription_dir, exist_ok=True)

    # Create tables (in dev; use alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")

    yield

    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="AI Helper API",
    description="AI-assisted negotiation helper for construction industry",
    version="1.0.0",
    lifespan=lifespan,
)

# In dev mode, allow all localhost origins

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger.info(f">> {request.method} {request.url.path} (origin: {request.headers.get('origin', '-')})")
        try:
            response = await call_next(request)
            logger.info(f"<< {request.method} {request.url.path} -> {response.status_code}")
            return response
        except Exception as exc:
            logger.error(f"XX {request.method} {request.url.path} -> ERROR: {exc}", exc_info=True)
            raise


# Order matters: add_middleware uses LIFO — last added = outermost.
# CORSMiddleware must be outermost to handle OPTIONS preflight BEFORE anything else.
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost(:\d+)?|meridian\.fvds\.ru(:\d+)?)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routes
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(providers_router, prefix="/api/settings/providers", tags=["settings"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(documents_router, prefix="/api/documents", tags=["documents"])
app.include_router(meetings_router, prefix="/api/transcriptions", tags=["meetings"])
app.include_router(roles_router, prefix="/api/roles", tags=["roles"])
app.include_router(history_router, prefix="/api/meetings", tags=["meetings-history"])
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
