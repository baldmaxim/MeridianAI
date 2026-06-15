# MERIDIAN — AI-ассистент для переговоров

Веб-приложение для помощи в переговорах в строительной сфере: транскрипция в реальном времени + LLM подсказки. Поддерживает загрузку PDF (договоры, ВОР, сметы) как контекст для подсказок.

## Стек

- **Backend:** FastAPI + SQLAlchemy async + PostgreSQL
- **Frontend:** React 19 + TypeScript + Vite + Zustand
- **Auth:** email + пароль (JWT/bcrypt); целевой путь — Keycloak OIDC (`AUTH_MODE=local|keycloak|both`)
- **Realtime:** WebSocket (аудио PCM 16kHz → транскрипция → LLM подсказки)
- **STT:** ElevenLabs / Deepgram / Gemini (streaming) · **LLM:** OpenRouter

## Быстрый старт (dev)

```bash
# Всё одной командой (инфра → миграции → backend + frontend)
meridian-web\start_dev.bat
```

Или вручную:

```bash
# 0. Dev-инфраструктура (PostgreSQL + MinIO)
cd meridian-web
docker compose -f docker-compose.dev.yml up -d --wait

# 1. Миграции БД (отдельный шаг, не из приложения)
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head

# 2. Backend (терминал A) — порт 8001
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# 3. Frontend (терминал B)
cd ..\frontend
npm run dev
```

> Схема БД создаётся только миграциями Alembic. Изменение модели → `alembic revision --autogenerate` → вычитать → коммит.

## Конфигурация

Настройки в `meridian-web/backend/.env`. Ключи и секреты (STT/LLM API, JWT_SECRET, ENCRYPTION_KEY) добавляет пользователь вручную — в репозиторий не коммитятся.

## Деплой

Образы собираются в CI (GitHub Actions) → GHCR. На vds — только `docker pull` готовых образов + миграции + `up` (без сборки на проде). Прод: https://meridian.fvds.ru
