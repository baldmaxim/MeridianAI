# CLAUDE.md

## Project Overview

AI-ассистент для помощи в переговорах в строительной сфере с транскрипцией в реальном времени и LLM подсказками.

**Веб-приложение** (FastAPI + React) в `meridian-web/`, доступ через браузер.

Работает с ElevenLabs/Deepgram/Gemini (транскрипция) и OpenRouter (LLM). Поддерживает загрузку PDF документов (договоры, ВОР, сметы) как контекст для подсказок.

---

## Корпоративный стандарт v3.1

Проект работает по корп. стандарту: **`corp_standard_full_single_vps.md`** (корень репозитория) — источник правды по архитектуре, auth, миграциям, файлам, jobs, deployment, observability, secrets.

Корп. скилы установлены в `.claude/skills/` (corp-*, agentic-*). Для задач по auth/БД/файлам/деплою использовать соответствующий скил (`corp-keycloak-oidc`, `corp-jobs-outbox`, `corp-files-presigned-s3`, `corp-deploy-compose`, `corp-security-review` и т.д.).

### Зафиксированные отступления от стандарта

| Стандарт требует | У нас | Причина |
|---|---|---|
| Node.js + TypeScript + Fastify | **FastAPI/Python остаётся** | Рабочий realtime STT-пайплайн ~7.6k LOC; применяем инфра/security/ops требования стандарта к FastAPI |
| Drizzle ORM + Drizzle Kit | **SQLAlchemy + Alembic** (SQL-first, versioned) | Следствие Python-стека |
| Ant Design 5 | **Кастомный UI** (бренд MERIDIAN) | Сохранение визуального бренда |
| Yandex Cloud (Managed PG, ALB, Lockbox) | **Текущий VPS «по духу»**: nginx ingress, PG в Docker с бэкапами, S3-совместимое хранилище, /opt/portals + /opt/infra | Миграция в Yandex Cloud — отдельный этап позже |
| Standalone auth §13 (refresh rotation и т.д.) | **Отложено** | Keycloak — целевой путь; local auth — переходный fallback |
| Образы из registry, без build на проде (§19) | **Сборка локально, на vds — только копирование** готовых артефактов (`docker save`/`load` или registry pull). Build на vds запрещён | Соответствует §19. host-nginx на :443, портал публикует edge на 127.0.0.1:8080. Переходно (нет CI/registry): образы собираются на dev-машине и переносятся на vds |

### Always-on правила (обязательны)

- **Секреты/PII**: никогда не добавлять в код, логи, тесты, доки, снапшоты, планы. Маскировать токены, пароли, Authorization, cookies, presigned URLs в логах.
- **Файлы**: production-загрузка только через presigned URL (после фазы 5 трансформации); backend не проксирует байты файлов.
- **Docker**: запрещены глобальные destructive-команды: `docker system prune -a`, `docker compose down --volumes`, `docker stop $(docker ps -q)`, `rm -rf /opt/portals/*`.
- **Деплой**: только portal-scoped — деплой Meridian не трогает nginx, Keycloak и соседние сервисы VPS (Xray, Supabase). Никаких `git pull`/`npm install`/build на production VPS — только готовые образы из registry с immutable tags.
- **Сборка**: СНАЧАЛА собрать локально (dev/CI), ПОТОМ выложить. На vds — только `docker load` готовых образов + `up`. Никакого `docker build`/`npm`/`pip`/vite на vds (1.8 GiB RAM + соседи — сборка душит box). Поток: `docker build` → `docker save | ssh vds docker load` → `ssh vds` migrate + `up -d`.
- **Схема БД**: любое изменение = новая Alembic-миграция. Никаких `create_all`/ad-hoc ALTER в prod. Миграции не редактируются задним числом — ошибка исправляется новой миграцией. Миграции применяются отдельным deployment-шагом, не из app-контейнера.
- **Зависимости**: перед добавлением/обновлением — freshness-check (`corp-freshness-check`): официальные доки, changelog, advisories, совместимость.
- **Многошаговые задачи**: вести `.ai/task_plan.md`, `.ai/findings.md`, `.ai/progress.md`, если пользователь не попросил иначе.

### Keycloak (SSO)

- Корпоративный Keycloak: `auth.su10.ru`, realm `su10`. Meridian — OIDC confidential client.
- **Не отключать local auth** во время миграции на Keycloak без feature flag (`AUTH_MODE=local|keycloak|both`) и плана отката.
- **Не удалять локальные роли** пользователей при SSO-миграции.
- Identity linking (`user_identities`) сохраняет роли существующих пользователей; роль из Keycloak мапится только при создании нового юзера.
- Backend проверяет: JWT signature, issuer, audience, expiration, client roles (§12).

---

## Стек

- **Backend:** FastAPI + SQLAlchemy async + PostgreSQL (SQLite dev — выпиливается в фазе 1)
- **Frontend:** React 19 + TypeScript + Vite + Zustand v5
- **Auth:** email + пароль, JWT (python-jose, HS256), bcrypt; целевой путь — Keycloak OIDC
- **Realtime:** WebSocket для аудио/транскрипции/подсказок
- **Аудио:** Browser AudioWorklet → PCM 16kHz Int16 → WS binary frames

## Структура

```
meridian-web/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, LoggingMiddleware
│   │   ├── config.py            # Settings из .env (Pydantic)
│   │   ├── database.py          # SQLAlchemy async engine
│   │   ├── models/              # ORM: User, ApiKey, UserSettings, MeetingSession, SavedTranscription
│   │   ├── schemas/             # Pydantic: auth, meeting, settings
│   │   ├── auth/                # register, login, JWT, bcrypt (без passlib)
│   │   ├── api/                 # REST: admin, settings, documents, meetings, batch, history, roles
│   │   ├── ws/handler.py        # WebSocket /ws/meeting — ядро (аудио, транскрипция, LLM)
│   │   ├── services/            # SessionManager, AudioBridge
│   │   └── core/                # transcription, context, llm, batch
│   ├── alembic/                 # SQL-first миграции (versioned)
│   ├── requirements.txt
│   └── .env                     # DATABASE_URL, JWT_SECRET, ENCRYPTION_KEY
├── frontend/
│   ├── src/
│   │   ├── api/                 # Axios client (baseURL: /api), auth, documents, settings, meetings
│   │   ├── hooks/               # useWebSocket, useAudioRecorder, useAuth
│   │   ├── components/          # auth/, meeting/, context/, settings/, admin/, layout/
│   │   ├── pages/               # LoginPage, MeetingPage, AdminPage
│   │   ├── store/meetingStore.ts # Zustand store
│   │   └── styles/theme.ts      # Dark theme (MERIDIAN)
│   └── package.json
├── deploy/                      # (фаза 3) portal compose, infra-nginx, deploy.sh, runbook
└── start_dev.bat                # Запуск backend + frontend одной командой
```

## Запуск (dev)

```bash
# Вариант 1: через bat файл (поднимает инфру → миграции → backend+frontend)
meridian-web\start_dev.bat

# Вариант 2: вручную
# 0. Dev-инфраструктура (PostgreSQL + MinIO):
cd meridian-web
docker compose -f docker-compose.dev.yml up -d --wait

# 1. Миграции БД (§8 — отдельный шаг, НЕ из приложения):
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head

# 2. Terminal A — Backend:
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# 3. Terminal B — Frontend:
cd ..\frontend
npm run dev
```

> Схема БД создаётся **только** миграциями Alembic. `create_all`/ad-hoc ALTER из рантайма удалены (§8).
> Новое изменение модели → `alembic revision --autogenerate -m "..."` → вычитать → коммит.

## Команды

### Frontend (meridian-web/frontend)
```bash
npm run dev        # vite dev server
npm run build      # tsc -b && vite build (типчек + прод-сборка)
npm run lint       # eslint . (ESLint 9 flat config)
npm run preview    # предпросмотр прод-сборки
```
> Vitest/Jest и Prettier НЕ настроены. Отдельной typecheck-команды нет — проверка типов внутри `build`. Vite proxy на backend НЕ настроен.

### Backend (meridian-web/backend)
```bash
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001 --reload   # запуск
..\.venv\Scripts\python.exe -m alembic upgrade head                        # применить миграции
..\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "..."    # новая миграция
```
> Тестов нет (`pytest` в requirements, но `tests/` отсутствует). Линтера (ruff/black/mypy) нет.
> Alembic — async engine; `migration_database_url` = юзер `meridian_migration` (DDL), runtime = `meridian_runtime` (DML). Роли создаёт `backend/db/init/01-users.sql`.

### Deploy (meridian-web/deploy)
> Рабочий путь — CI/GHCR: push в `main` → `.github/workflows/deploy.yml` собирает образы → на vds `deploy-ghcr.sh`.
> Скрипты: `build.sh` / `build-local.sh` (dev→prod), `deploy.sh` (на VPS, health-gate + flock), `deploy-ghcr.sh` (pull из GHCR).

## API

```
POST   /api/auth/register, /api/auth/login, GET /api/auth/me
POST   /api/documents/upload, DELETE /api/documents/{filename}
GET/PUT /api/settings
POST   /api/transcriptions/save, GET /api/transcriptions, GET .../download?token=<jwt>
GET    /api/admin/users, PUT .../users/{id}
CRUD   /api/admin/api-keys
WS     /ws/meeting?token=<jwt>
GET    /health/live, /health/ready   # (фаза 2)
```

## WebSocket протокол (ws://host/ws/meeting?token=jwt)

**Client → Server:**
- Binary frames: PCM 16-bit 16kHz mono (~100ms чанки)
- JSON: `start_listening`, `stop_listening`, `request_suggestion`, `strengthen_position`, `mark_speaker`, `update_meeting_context`

**Server → Client (JSON):**
- `transcript` (speaker, text, timestamp, is_partial)
- `suggestion` / `suggestion_chunk` (streaming)
- `suggestion_loading` / `strengthen_loading`
- `error`, `status`

## Важные решения

- **CORS:** точный allowlist origins (после фазы 2; ранее regex). CORSMiddleware добавлен ПОСЛЕДНИМ через `add_middleware()` (LIFO → outermost)
- **bcrypt:** Используем напрямую (не passlib) — passlib несовместим с bcrypt>=5.0
- **API client:** `baseURL` включает `/api` prefix, endpoints без дублирования
- **Download:** Query token auth (`?token=jwt`) вместо Bearer header (для прямых ссылок)
- **Audio feedback:** Silent GainNode предотвращает проигрывание микрофона в колонки

## Тестовый пользователь

- email: `admin@test.com`, password: `admin123`, role: admin (только dev)

---

## Брендинг MERIDIAN

Визуальная концепция определена в `branding/meridian.html` и `branding/meridian-logos.html`.

### Цветовая палитра
- **Backgrounds**: #080A0F (void), #0D1018 (deep), #111520 (surface), #161C2C (elevated), #1A2135 (card)
- **Primary accent**: #F5A623 (amber), #C4851A (amber-dim)
- **Status**: #2EE59D (green), #FF4B6E (red), #5B9CF6 (blue)
- **Text**: #EDF2FF (primary), #8896B3 (secondary), #4A5568 (muted)

### Шрифты
- **Syne** (800) — заголовки, бренд
- **JetBrains Mono** — моноширинный, метки, техническая информация
- **Inter** — основной текст UI

### Логотип
SVG компас/прицел с концентрическими кругами. Варианты в `branding/meridian-logos.html` (#01-#07).

---

## Адаптивность (обязательно)

Все UI компоненты ОБЯЗАНЫ быть адаптированы под:

- **iPhone 15 Pro Max** (430 × 932 px)
- **iPhone 12** (390 × 844 px)
- **iPad** (768 × 1024 px и больше)

Использовать CSS media queries для корректного отображения на всех целевых устройствах.

Breakpoints:
- ≥1024px — Desktop (2-panel layout)
- 768–1023px — Tablet/iPad (collapsible right panel)
- <768px — Mobile (single column, sticky controls)

---

## Анимации (стандарт — transitions.dev)

Единственный стандарт анимаций. Это **не npm-пакет**, а copy-paste CSS-переходы. Источник — скил `.agents/skills/transitions-dev/` (12 переходов, verbatim). В проекте:

- CSS: `frontend/src/styles/transitions.css` (классы `t-*`, токены в `:root`, у каждого `prefers-reduced-motion`-guard). Подключается в `main.tsx` после `index.css`.
- React-примитивы: `frontend/src/components/common/` — `Modal`, `Dropdown`, `IconSwap`, `NotificationBadge`, `PageTransition`, `AvatarGroup`, `CardResize`, `PopNumber`, `TextSwap`, `SuccessCheck`. Хуки: `useExitTransition`, `useOpenClose`, `useErrorShake`.
- Каталог «что для чего» + примеры: `frontend/src/components/common/README.md`.

Правила для новых разработок:
- Любую новую анимируемую поверхность делать через примитивы из `components/common/` или классы `t-*`. Не вводить framer-motion и др. motion-библиотеки.
- Не использовать `transition: all`; сохранять `prefers-reduced-motion`; тюнинг только через токены `:root`.
- Новый переход из каталога — копировать из скила **verbatim** (не переписывать селекторы).
- Скил триггерится на «добавь переход», «анимируй дропдаун», «success animation»; команды `transitions reveal/review/apply`.

---

## MVP

- Всегда делай минимально работающую версию
- Не добавляй фичи "на будущее"
- Сначала работает — потом улучшаем

## КРАТКОСТЬ

- Отвечай максимально сжато. Без пояснений и предисловий.
- Если запрашивают код — выводи только рабочие фрагменты кода в блоках, без текста.
- Изменения выдавай как *минимальный diff/patch* или как *конкретные вставки*.
- Не перечисляй, «что было сделано», если прямо не попросили.
- Если нужен текст — не более 5 пунктов, каждый ≤ 12 слов.

## .env

- НИКОГДА не изменять `.env` файлы (`frontend/.env`, `backend/.env`)
- Ключи и URL добавляет только пользователь вручную
- Production-секреты — только в protected secret storage (§18), не в образах/коде/логах/БД

## Git

- Коммиты на русском, кратко (1-2 предложения)
- Без приписок "Generated with Claude Code" и "Co-Authored-By"

---

## План трансформации под стандарт

Фазы (план: `C:\Users\Usrr\.claude\plans\1-corp-standard-full-single-vps-md-dynamic-feather.md`):

- ✅ **0** — CLAUDE.md + корп. скилы
- ✅ **1** — PostgreSQL везде + Alembic baseline (runtime/migration DB users) · live-проверка `alembic upgrade head` ждёт запуска Docker
- ✅ **2** — Hardening: JSON-логи с редакцией, /health/*, startup checks, фикс path traversal, rate limit, Sentry backend · верифицировано TestClient 13/13
- ✅ **3** — Деплой: deploy/portal compose + infra-nginx + build.sh/deploy.sh с health gates · compose/скрипты валидны
- ✅ **3-FVDS** — Боевой передеплой на vds (2026-06-11): `/opt/portals/meridian`, build-на-сервере, edge на 127.0.0.1:8080, свежая БД + бэкап старой, §7 роли. Соседи (Xray/VPN/Supabase) не тронуты. Live: https://meridian.fvds.ru health 200/200, auth/rate-limit/headers ✓
- ✅ **4** — Jobs: PG-таблица jobs (§16), worker-процесс, batch через outbox · на проде (worker claim/dispatch/complete проверены live; edge-resolver устойчив к рестартам api)
- ✅ **5** — Файлы: presigned S3 для batch-аудио (§15, upload-session/confirm, soft-delete, физ. удаление через job) · **вживую на проде** (cloud.ru, tenant-проект; server round-trip + браузерный CORS-preflight проверены). Graceful fallback на multipart без S3. Документы — пока multipart (под-шаг позже)
- ☐ **6** — Keycloak OIDC + identity linking + AUTH_MODE (session bridging)
- ✅ **7** — Audit log (§22): login/role/api-key/dead-job, email как HMAC, своя транзакция · на проде (login_failed → audit-запись с HMAC проверено live)
- ☐ **8** — Observability: Sentry frontend, uptime, алерты
- ✅ **CI/GHCR** — GitHub Actions собирает образы → GHCR (public) → vds `docker pull` (deploy-ghcr.sh). Локальный Docker сломан (cred-helper), vds-сборка = OOM. Это рабочий путь деплоя

## Known Issues

- ElevenLabs, Deepgram, Gemini и OpenRouter — платные API
- Gemini: НЕ true streaming, задержка ~5 сек
- venv общий (`.venv/` в корне), frontend node_modules в `meridian-web/frontend/`
- ✅ Path traversal в `app/api/documents.py` — пофикшено (фаза 2, `safe_filename`)
- ✅ Batch: 500MB в RAM / гибель при рестарте — пофикшено (фаза 4 jobs + фаза 5 presigned S3, аудио мимо backend)
- ✅ WS `?token=` в access-логах — пофикшено (фаза 2, `--no-access-log` + редакция)
- ☐ Документы (`/api/documents/upload`) пока multipart (маленькие, traversal закрыт). Перевод на presigned S3 — под-шаг фазы 5 позже
- ☐ Нет автотестов (backend/frontend) и линтеров (ruff/black/mypy) — добавить отдельной фазой
