"""Этап 25: retention cleanup CLI — dry-run по умолчанию, execute заблокирован без флагов,
cap по max meetings, safe JSON без raw titles/text."""

import json
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database import Base
from app.tools import retention_cleanup as rc
from tests.privacy_test_utils import make_sqlite_engine, mk_user, mk_meeting, add_transcript

_OLD = datetime.utcnow() - timedelta(days=400)
_RECENT = datetime.utcnow()


async def _sm_with_meetings(n_old: int):
    engine = make_sqlite_engine()
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as db:
        owner = await mk_user(db, "ret@t.local")
        for i in range(n_old):
            old = await mk_meeting(db, owner, started_at=_OLD, ended_at=_OLD,
                                   title=f"СекретнаяВстреча{i}")
            await add_transcript(db, old, text="секретный транскрипт цена")
        await mk_meeting(db, owner, started_at=_RECENT, title="СвежаяВстреча")
        await db.commit()
    return engine, sm


async def test_retention_dry_run_default(monkeypatch):
    engine, sm = await _sm_with_meetings(1)
    monkeypatch.setattr(rc, "async_session", sm)
    try:
        result, code = await rc.run_cleanup(180, execute=False)
        assert code == 0 and result["mode"] == "dry_run"
        assert result["meeting_count"] == 1  # только старая (свежая вне окна)
        blob = json.dumps(result, ensure_ascii=False)
        assert "секретный транскрипт" not in blob and "СекретнаяВстреча" not in blob
    finally:
        await engine.dispose()


async def test_retention_execute_blocked_when_flags_disabled(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "retention_cleanup_enabled", False)
    monkeypatch.setattr(s, "privacy_hard_delete_enabled", False)
    result, code = await rc.run_cleanup(180, execute=True)
    assert code == 4 and result["status"] == "blocked"


async def test_retention_max_meetings_cap(monkeypatch):
    monkeypatch.setattr(get_settings(), "privacy_delete_max_meetings_per_run", 2)
    engine, sm = await _sm_with_meetings(5)
    monkeypatch.setattr(rc, "async_session", sm)
    try:
        result, code = await rc.run_cleanup(180, execute=False)
        assert result["meeting_count"] == 2 and result["skipped_count"] == 3
    finally:
        await engine.dispose()


def test_retention_output_file_safe(monkeypatch, tmp_path):
    # sync-тест: _main вызывает asyncio.run — run_cleanup застаблен (без БД/loop-конфликта)
    async def _stub(days, execute):
        return ({"status": "ok", "mode": "dry_run", "older_than_days": days, "meeting_count": 1,
                 "skipped_count": 0, "deleted_counts": {"transcript": 3}, "meeting_ids": [1],
                 "warnings": [], "errors": []}, 0)
    monkeypatch.setattr(rc, "run_cleanup", _stub)
    out_file = tmp_path / "ret.safe.json"
    code = rc._main(["prog", "--dry-run", "--output", str(out_file)])
    assert code == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["mode"] == "dry_run" and data["meeting_count"] == 1
    assert "Секрет" not in out_file.read_text(encoding="utf-8")  # нет raw titles


async def test_retention_output_hashes_ids(monkeypatch):
    # Этап 26 fix: в выводе только хэши meeting_id, без raw id
    engine, sm = await _sm_with_meetings(1)
    monkeypatch.setattr(rc, "async_session", sm)
    try:
        result, code = await rc.run_cleanup(180, execute=False)
        assert "meeting_id_hashes" in result and "meeting_ids" not in result
        assert result["meeting_count"] == 1
        assert all(isinstance(h, str) and len(h) == 16 for h in result["meeting_id_hashes"])
    finally:
        await engine.dispose()


async def test_retention_execute_deletes(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "retention_cleanup_enabled", True)
    monkeypatch.setattr(s, "privacy_hard_delete_enabled", True)
    monkeypatch.setattr(s, "privacy_delete_require_dry_run_first", True)
    engine, sm = await _sm_with_meetings(1)
    monkeypatch.setattr(rc, "async_session", sm)
    try:
        result, code = await rc.run_cleanup(180, execute=True)
        assert code == 0 and result["mode"] == "execute"
        assert result["meeting_count"] == 1 and not result["errors"]
    finally:
        await engine.dispose()
