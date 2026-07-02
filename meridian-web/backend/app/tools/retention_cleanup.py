"""Retention cleanup CLI (Этап 25).

Находит старые встречи (по ended_at/started_at) и удаляет их данные — но БЕЗОПАСНО:
- по умолчанию dry-run (ничего не удаляет);
- --execute требует RETENTION_CLEANUP_ENABLED=true И PRIVACY_HARD_DELETE_ENABLED=true;
- не больше PRIVACY_DELETE_MAX_MEETINGS_PER_RUN за прогон;
- вывод строго JSON: counts по категориям, meeting_count, skipped_count, warnings (без raw
  titles/filenames/transcript text).

CLI:
  python -m app.tools.retention_cleanup --dry-run
  python -m app.tools.retention_cleanup --dry-run --older-than-days 180
  python -m app.tools.retention_cleanup --execute --older-than-days 180
Exit: 0 ок; 2 ошибка/БД; 3 неверные аргументы; 4 execute заблокирован флагами.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta

from sqlalchemy import func, select

from ..config import get_settings
from ..core.context.canary_trace_filter import hash_filter_token
from ..core.privacy.privacy_audit import log_privacy_event
from ..database import async_session
from ..models.meeting import MeetingSession
from ..services.privacy_delete_service import PrivacyDeleteService, _make_confirmation_token

logger = logging.getLogger("meridian.privacy")

_FULL_FLAGS = {"include_documents": True, "include_audio": True, "include_meeting_record": True}


async def run_cleanup(older_than_days: int, execute: bool) -> tuple[dict, int]:
    s = get_settings()
    result = {
        "status": "ok", "mode": "execute" if execute else "dry_run",
        "older_than_days": older_than_days, "meeting_count": 0, "skipped_count": 0,
        "deleted_counts": {}, "meeting_id_hashes": [], "warnings": [], "errors": [],
    }
    if execute and not (s.retention_cleanup_enabled and s.privacy_hard_delete_enabled):
        result["status"] = "blocked"
        result["warnings"].append(
            "execute requires RETENTION_CLEANUP_ENABLED=true and PRIVACY_HARD_DELETE_ENABLED=true")
        return result, 4

    cutoff = datetime.utcnow() - timedelta(days=max(0, older_than_days))
    max_n = int(s.privacy_delete_max_meetings_per_run)
    svc = PrivacyDeleteService()
    agg: dict[str, int] = {}
    try:
        async with async_session() as db:
            cond = func.coalesce(MeetingSession.ended_at, MeetingSession.started_at) < cutoff
            total = (await db.execute(
                select(func.count()).select_from(MeetingSession).where(cond))).scalar() or 0
            ids = list((await db.execute(
                select(MeetingSession.id).where(cond).order_by(MeetingSession.id).limit(max_n)
            )).scalars().all())
            if total > max_n:
                result["skipped_count"] = total - max_n
                result["warnings"].append(f"capped at max {max_n} meetings per run")

            for mid in ids:
                if execute:
                    token = _make_confirmation_token(mid, None, _FULL_FLAGS)
                    rep = await svc.execute_delete_plan(
                        db, mid, None, dry_run=False, confirmation_token=token, **_FULL_FLAGS)
                    if rep.blockers:
                        result["errors"].extend(rep.blockers)
                        continue
                else:
                    rep = await svc.execute_delete_plan(db, mid, None, dry_run=True, **_FULL_FLAGS)
                for k, v in rep.deleted_counts.items():
                    agg[k] = agg.get(k, 0) + int(v)
                result["meeting_id_hashes"].append(hash_filter_token(str(mid)))  # без raw id в evidence
            result["meeting_count"] = len(result["meeting_id_hashes"])
            result["deleted_counts"] = agg
    except Exception as e:  # noqa: BLE001
        result["status"] = "error"
        result["errors"].append(type(e).__name__)
        return result, 2

    log_privacy_event(logger, "retention_cleanup_executed" if execute else "retention_cleanup_dry_run",
                      counts=agg, warnings=result["warnings"])
    return result, 0


def _main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.retention_cleanup",
        description="Безопасная retention-очистка старых встреч (Этап 25). Default dry-run.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--older-than-days", type=int, default=None)
    parser.add_argument("--output", default=None)
    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3

    days = ns.older_than_days if ns.older_than_days is not None else get_settings().retention_default_days
    result, code = asyncio.run(run_cleanup(int(days), execute=bool(ns.execute)))
    blob = json.dumps(result, ensure_ascii=False, indent=2)
    if ns.output:
        try:
            with open(ns.output, "w", encoding="utf-8") as f:
                f.write(blob)
        except OSError as e:
            print(f"Ошибка записи: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"written": ns.output, "meeting_count": result.get("meeting_count"),
                          "mode": result.get("mode")}, ensure_ascii=False))
    else:
        print(blob)
    return code


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
