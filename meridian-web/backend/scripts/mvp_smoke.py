"""MVP smoke-check (Этап 10): быстрая проверка готовности backend без LLM-вызовов.

Запуск (из meridian-web/backend):
    ../.venv/Scripts/python.exe scripts/mvp_smoke.py

Проверяет: импорт app, подключение к БД, текущую alembic-ревизию, наличие ключевых
роутов, безопасную сводку конфигурации и (опц.) связность S3. Не создаёт встреч,
не дёргает платные API. Код возврата != 0, если БД недоступна или нет ключевого роута.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

REQUIRED_ROUTES = [
    "/api/health",
    "/api/health/deep",
    "/api/health/jobs",
    "/api/health/config-summary",
    "/api/ai-settings/profiles",
    "/api/ai-settings/options",
    "/api/meetings/{meeting_id}/ai-settings",
    "/api/meetings/{meeting_id}/context-sources",
    "/api/meetings/{meeting_id}/context-candidates",
    "/api/documents/upload-session",
    "/ws/meetings/{meeting_id}",
]


async def main() -> int:
    ok = True
    from app.main import app
    from app.config import get_settings
    from app.database import engine

    s = get_settings()
    print(f"[smoke] version={s.app_version} environment={s.environment} dev_mode={s.dev_mode}")

    # 1) БД + alembic revision
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
            rev = (await c.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        print(f"[smoke] DB: ok, alembic_revision={rev}")
    except Exception as e:
        print(f"[smoke] DB: ERROR {type(e).__name__}")
        ok = False

    # 2) ключевые роуты
    paths = {getattr(r, "path", "") for r in app.routes}
    for p in REQUIRED_ROUTES:
        present = p in paths
        print(f"[smoke] route {p}: {'OK' if present else 'MISSING'}")
        ok = ok and present

    # 3) безопасная сводка конфигурации (без секретов)
    print("[smoke] config_summary: " + json.dumps(s.safe_config_summary(), ensure_ascii=False))

    # 4) S3 (опционально)
    if s.s3_enabled:
        try:
            from app.services import s3
            reachable, detail = await s3.ping()
            print(f"[smoke] S3: configured, reachable={reachable} ({detail})")
        except Exception as e:
            print(f"[smoke] S3: ERROR {type(e).__name__}")
    else:
        print("[smoke] S3: not configured")

    await engine.dispose()
    print(f"[smoke] RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
