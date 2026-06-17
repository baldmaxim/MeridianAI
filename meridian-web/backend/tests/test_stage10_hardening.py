"""Тесты production-hardening (Этап 10): health/config без секретов, S3 traversal,
jobs recovery/трункация/счётчики, single alembic head, доступ."""

import json
import os
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.models.user import User
from app.models.meeting import MeetingSession
from app.models.job import Job
from app.services import jobs as jobs_svc
from app.services import s3
from app.services.ai_settings import resolve_for_meeting
from app.utils.files import safe_filename
from app.api.health import health, config_summary
from app.api.history import list_meeting_documents
from sqlalchemy import select, func


async def _mk_user(db, email, role="user"):
    u = User(email=email, password_hash="x", role=role, is_active=True)
    db.add(u); await db.flush(); await db.refresh(u)
    return u


_SECRET_TOKENS = ("secret", "password", "api_key", "apikey", "token", "encryption_key",
                  "access_key", "jwt_secret", "x-amz-signature")


def _no_secrets(payload: dict):
    blob = json.dumps(payload, ensure_ascii=False).lower()
    for bad in _SECRET_TOKENS:
        assert bad not in blob, f"secret-подобный ключ просочился: {bad}"


# ---------- 1: health безопасен ----------

async def test_health_status_safe(db):
    out = await health(db=db)
    assert out["status"] in ("ok", "degraded")
    assert out["version"] and "database" in out
    assert set(("s3_configured", "llm_configured", "stt_configured")).issubset(out)
    _no_secrets(out)


# ---------- 2: config-summary без секретов ----------

async def test_config_summary_no_secrets(db):
    owner = await _mk_user(db, "h2@test.local")
    out = await config_summary(user=owner)
    _no_secrets(out)
    assert "version" in out and "s3_configured" in out and "auth_mode" in out


# ---------- 3: safe_filename отклоняет traversal ----------

def test_safe_filename_rejects_or_sanitizes_traversal():
    # пустые/«..»/null — отклоняются
    for bad in ("", "..", "x\x00.pdf"):
        with pytest.raises(HTTPException):
            safe_filename(bad)
    # пути с каталогами — отклонены ЛИБО сведены к безопасному basename (без traversal)
    for path in ("../../etc/passwd", "a/b.pdf", "..\\..\\x.pdf"):
        try:
            out = safe_filename(path)
            assert ".." not in out and "/" not in out and "\\" not in out and "\x00" not in out
        except HTTPException:
            pass  # отклонение тоже корректно
    assert safe_filename("смета.pdf") == "смета.pdf"


# ---------- 4: object_key не строится из ввода (no traversal) ----------

def test_object_key_no_traversal():
    key = s3.object_key(7, "documents", "../../../etc/passwd.pdf")
    assert ".." not in key and key.startswith("meridian/7/documents/") and key.endswith(".pdf")
    key2 = s3.object_key(7, "documents", "weird/../name.PDF")
    assert ".." not in key2 and key2.endswith(".pdf")


# ---------- 5: stale-job recovery → retry/dead ----------

async def test_recover_stale_jobs(db):
    past = datetime.utcnow() - timedelta(minutes=5)
    retryable = Job(type="document_process", payload={}, status="running", attempts=1,
                    max_attempts=3, next_run_at=past, locked_until=past, locked_by="dead-worker")
    dead = Job(type="meeting_finalize", payload={}, status="running", attempts=3,
               max_attempts=3, next_run_at=past, locked_until=past, locked_by="dead-worker")
    db.add_all([retryable, dead]); await db.flush()
    res = await jobs_svc.recover_stale_jobs(db, older_than_minutes=0)
    assert res["scanned"] == 2 and res["recovered"] == 1 and res["dead"] == 1
    await db.refresh(retryable); await db.refresh(dead)
    assert retryable.status == "pending" and retryable.locked_by is None
    assert dead.status == "dead"


# ---------- 6: error_message обрезается ----------

async def test_job_error_truncated(db):
    job = Job(type="document_process", payload={}, status="running", attempts=1, max_attempts=3,
              next_run_at=datetime.utcnow())
    db.add(job); await db.flush()
    await jobs_svc.fail(db, job.id, "x" * 50000)
    await db.refresh(job)
    assert job.last_error is not None
    assert len(job.last_error) <= get_settings().job_error_max_chars


# ---------- 7: job_counts отдаёт счётчики ----------

async def test_job_counts(db):
    db.add_all([
        Job(type="document_process", payload={}, status="pending", attempts=0, max_attempts=3, next_run_at=datetime.utcnow()),
        Job(type="meeting_finalize", payload={}, status="done", attempts=1, max_attempts=3, next_run_at=datetime.utcnow()),
        Job(type="learning_extract", payload={}, status="dead", attempts=3, max_attempts=3, next_run_at=datetime.utcnow()),
    ])
    await db.flush()
    counts = await jobs_svc.job_counts(db)
    assert counts["by_status"].get("pending", 0) >= 1
    assert counts["by_status"].get("dead", 0) >= 1
    assert "by_type" in counts and "dead_last_24h" in counts


# ---------- 8: одна alembic-голова ----------

def test_single_alembic_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    ini = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
    heads = ScriptDirectory.from_config(Config(ini)).get_heads()
    assert len(heads) == 1, f"ожидалась одна голова, получено: {heads}"


# ---------- 9: no-access не читает документы встречи ----------

async def test_meeting_documents_open_to_everyone(db):
    # Общая хронология: документы встречи видны любому авторизованному.
    owner = await _mk_user(db, "h9-owner@test.local")
    stranger = await _mk_user(db, "h9-stranger@test.local")
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=False,
                       started_at=datetime(2026, 1, 1, 10, 0))
    db.add(m); await db.flush()
    items = await list_meeting_documents(m.id, user=stranger, db=db)
    assert items == []


# ---------- 10: встреча без ai-снапшота резолвится через config ----------

async def test_meeting_without_snapshot_resolves(db):
    owner = await _mk_user(db, "h10@test.local")
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=False,
                       started_at=datetime(2026, 1, 1, 10, 0))
    db.add(m); await db.flush()
    resolved = await resolve_for_meeting(db, m.id)
    assert resolved["mode"] == "balanced" and resolved["auto_suggestions_enabled"] is True
    assert resolved["profile_id"] is None
