# MVP Runbook — MeridianAI

Запуск и проверка MVP (backend FastAPI + worker + frontend Vite).

## Требования
- Python 3.12+ (venv в `meridian-web/.venv`), Node 20+
- PostgreSQL (Yandex Managed или Docker), S3-совместимое хранилище (опц.), ключи API (OpenRouter/STT) — задаёт пользователь
- Миграции БД применяются ОТДЕЛЬНЫМ шагом (§8), не из приложения

## ENV (backend/.env — правит только пользователь)
Обязательные: `DATABASE_URL` (postgresql+asyncpg://…), `JWT_SECRET`, `ENCRYPTION_KEY`.
Опциональные: `MIGRATION_DATABASE_URL`, `S3_ENDPOINT/S3_BUCKET/S3_ACCESS_KEY/S3_SECRET_KEY`,
`AUTH_MODE`, `OIDC_*`, `SENTRY_DSN`. Hardening (Этап 10): `APP_VERSION`, `JOB_MAX_ATTEMPTS`,
`JOB_RETRY_BASE_SECONDS`, `JOB_ERROR_MAX_CHARS`, `JOB_STALE_RUNNING_MINUTES`,
`WORKER_POLL_INTERVAL_SECONDS`, `WS_MAX_BINARY_FRAME_BYTES`, `MEETING_ROOM_IDLE_TTL_MINUTES`,
`AUDIO_MAX_UPLOAD_MB`, `DOCUMENT_MAX_UPLOAD_MB`.
API-ключи STT/LLM хранятся в БД (зашифрованы), не в .env.

## 1. Миграции
```
cd meridian-web/backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic current      # должно показать head (0012)
```

## 2. Backend
```
cd meridian-web/backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

## 3. Worker (отдельный процесс — обязателен для документов/финализации/обучения)
```
cd meridian-web/backend
..\.venv\Scripts\python.exe -m app.worker
```

## 4. Frontend
```
cd meridian-web/frontend
npm install
npm run dev      # или npm run build для прод-сборки
```

## 5. Smoke-проверка
```
cd meridian-web/backend
..\.venv\Scripts\python.exe scripts\mvp_smoke.py     # PASS/FAIL
```

## Проверка здоровья
- `GET /api/health` — публичный: status, version, database, s3/llm/stt_configured
- `GET /api/health/jobs` — счётчики очереди (нужна авторизация)
- `GET /api/health/config-summary` — безопасные флаги (без секретов)
- `GET /api/health/deep` — admin/dev: db, alembic current/head, S3 ping, jobs
- `GET /health/live` / `GET /health/ready` — liveness/readiness (k8s)

## Сценарные проверки
- **S3 upload:** `POST /api/documents/upload-session` → PUT на presigned URL → `POST .../confirm` → worker `document_process` → статус `ready` (видно в `/api/meetings/{id}/documents`).
- **Phone recorder:** открыть `/recorder/{meeting_id}` на телефоне (тот же JWT), «начать запись» → desktop получает транскрипт по WS.
- **Finalization:** завершить встречу → job `meeting_finalize` → протокол (`/api/meetings/{id}/protocol`). Если выключено в AI-профиле — статус `disabled`.
- **Learning:** после финализации job `learning_extract` → кандидаты в `/api/learning/candidates` → approve → знание в `/api/knowledge/*`.
- **Previous meetings:** на подготовке встречи добавить прошлую встречу (`/api/meetings/{id}/context-sources`) → её итоги попадают в подсказки.
- **AI settings:** `/settings/ai` (кнопка «AI-профили») — профиль/режим/тогглы; на встрече `/api/meetings/{id}/ai-settings`.

## Типовые ошибки
- **Документ «висит» в `uploaded/processing`** → не запущен worker. Запустить `python -m app.worker`.
- **`S3-хранилище не настроено` (503)** → не заданы `S3_*` в .env. Документы недоступны, остальное работает.
- **`STT provider is not configured`** → нет ключа STT в БД (раздел админа/ключи).
- **`/api/health/deep` 403** → нужен admin или `DEV_MODE=true`.
- **Зависшие `running` job после падения воркера** → авто-восстановление при старте воркера + `POST /api/health/jobs/recover-stale` (admin/dev).
- **Несколько alembic heads** → проверить `alembic heads`; должна быть одна (0012).
