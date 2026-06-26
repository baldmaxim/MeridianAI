<div align="center">

<img src="docs/assets/meridian-banner.svg" alt="MERIDIAN — AI-ассистент для переговоров" width="760">

### AI-ассистент для переговоров в строительстве

Транскрипция в реальном времени и **LLM-подсказки** прямо во время встречи — слушает разговор,
подтягивает контекст из договоров, ВОР и смет и подсказывает, что ответить.

<sub><b>Realtime negotiation copilot for the construction industry</b> · live transcription + context-aware LLM suggestions</sub>

<br/>

![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat-square&logo=vite&logoColor=white)
![WebSocket](https://img.shields.io/badge/Realtime-WebSocket-F5A623?style=flat-square)
![Status](https://img.shields.io/badge/status-MVP-2EE59D?style=flat-square)

[Возможности](#возможности) · [Архитектура](#архитектура) · [Быстрый старт](#быстрый-старт-dev) · [Конфигурация](#конфигурация) · [Деплой](#деплой) · [English](#in-english)

</div>

---

## Возможности

- 🎙 **Realtime-транскрипция** — потоковый STT (ElevenLabs / Deepgram / Gemini) с диаризацией спикеров
- 💡 **LLM-подсказки** — авто- и ручные подсказки во время разговора, режим «усилить позицию»
- 📄 **Контекст из документов** — PDF / DOCX / XLSX (договоры, ВОР, сметы): извлечение текста, чанкинг, RAG
- ✉️ **RAG по письмам** — гибридный поиск по внешней базе переписки (pgvector)
- 🧱 **Дерево общения** — live-извлечение договорённостей и существенных условий из диалога
- 📝 **Протокол встречи** — фоновая авто-финализация итогов через LLM
- 🎚 **Мультиканальный звук** — второй телефон как дополнительный аудиоисточник / диаризация
- 🗂 **История и роли** — сохранённые встречи, админка пользователей / API-ключей / ролей
- 📱 **Адаптивность** — iPhone, iPad, desktop (sticky-контролы на мобильном)
- 🎨 **Бренд MERIDIAN** — кастомный тёмный UI и анимации по стандарту transitions.dev

## Стек

| Слой | Технологии |
|---|---|
| **Backend** | FastAPI · SQLAlchemy (async) · PostgreSQL · Alembic |
| **Frontend** | React 19 · TypeScript · Vite · Zustand v5 |
| **Realtime** | WebSocket · Browser AudioWorklet (PCM 16 kHz Int16) |
| **Транскрипция** | ElevenLabs · Deepgram · Gemini |
| **LLM** | OpenRouter |
| **Auth** | email + JWT (bcrypt) → Keycloak OIDC (`AUTH_MODE=local\|keycloak\|both`) |
| **Хранилище** | S3-совместимое (presigned upload) |

## Архитектура

```mermaid
flowchart LR
  Mic["🎙 Browser AudioWorklet"] -->|"PCM 16 kHz · WS binary"| WS["FastAPI WS · /ws/meeting"]
  WS --> STT["STT<br/>ElevenLabs / Deepgram / Gemini"]
  STT -->|transcript| WS
  Docs["📄 PDF / DOCX / XLSX"] --> CTX["Context Pack + RAG"]
  Letters["✉️ Письма (pgvector)"] --> CTX
  WS --> CTX
  CTX --> LLM["LLM · OpenRouter"]
  LLM -->|"подсказки (streaming)"| WS
  WS -->|"transcript / suggestion"| UI["React UI"]
```

Аудио идёт из браузера бинарными WS-фреймами в backend, оттуда — в потоковый STT. Транскрипт вместе с
контекстом из документов и писем собирается в Context Pack и уходит в LLM; подсказки стримятся обратно в UI.

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

> Схема БД создаётся **только** миграциями Alembic. Изменение модели → `alembic revision --autogenerate` → вычитать → коммит.

## Конфигурация

Настройки — в `meridian-web/backend/.env` (Pydantic Settings). Ключи и секреты добавляет пользователь
вручную; в репозиторий они **не** коммитятся. Шаблон с описанием всех переменных:
[`meridian-web/deploy/portal/meridian.env.example`](meridian-web/deploy/portal/meridian.env.example).

```env
DATABASE_URL=postgresql+asyncpg://user:***@host:5432/db
JWT_SECRET=...
ENCRYPTION_KEY=...            # шифрование API-ключей в БД
# STT/LLM-ключи — в админке (хранятся зашифрованно) или через env
# S3 (опц.):       S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY
# Keycloak (опц.): AUTH_MODE, OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET
```

## Структура

```
meridian-web/
├── backend/                 # FastAPI + SQLAlchemy async
│   ├── app/
│   │   ├── main.py          # FastAPI app, CORS, logging
│   │   ├── config.py        # Settings из .env
│   │   ├── api/             # REST: admin, settings, documents, meetings, history, roles
│   │   ├── ws/handler.py    # WebSocket /ws/meeting — ядро (аудио, транскрипция, LLM)
│   │   ├── core/            # transcription, context, llm, batch
│   │   └── models/          # ORM
│   ├── alembic/             # SQL-first миграции (versioned)
│   └── requirements.txt
├── frontend/                # React 19 + TS + Vite + Zustand
│   └── src/                 # api/, hooks/, components/, pages/, store/, styles/
└── deploy/                  # portal compose, infra-nginx, deploy-скрипты
```

## Деплой

Образы собираются в CI (**GitHub Actions** → GHCR). На сервере — только `docker pull` готовых образов,
миграции отдельным шагом и `up`; **без сборки на проде**. Деплой portal-scoped — не трогает соседние сервисы
на хосте.

```bash
# на сервере (значения — через env / .deploy.env, см. шаблон)
OWNER=<org> DOMAIN=<домен> bash meridian-web/deploy/deploy-ghcr.sh
```

Значения деплоя (owner / домен / ssh / пути) — в [`meridian-web/deploy/.deploy.env.example`](meridian-web/deploy/.deploy.env.example);
реальные значения держатся локально и в репозиторий не попадают.

## In English

**MERIDIAN** is a realtime negotiation assistant for the construction industry. It transcribes a live
conversation, pulls context from uploaded contracts / bills of quantities / cost estimates, and streams
**LLM suggestions** on what to say next — with speaker diarization, a meeting protocol summary, and
document/letter RAG.

- **Backend:** FastAPI · SQLAlchemy (async) · PostgreSQL · Alembic
- **Frontend:** React 19 · TypeScript · Vite · Zustand
- **Realtime:** WebSocket, browser AudioWorklet (PCM 16 kHz) → STT (ElevenLabs / Deepgram / Gemini) → LLM (OpenRouter)

See [Quickstart](#быстрый-старт-dev) to run it locally. API keys and secrets are user-provided and never committed.

## Лицензия

Проприетарный проект — все права защищены. © MERIDIAN.
