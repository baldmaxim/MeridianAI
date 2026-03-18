# CLAUDE.md

## Project Overview

AI-ассистент для помощи в переговорах в строительной сфере с транскрипцией в реальном времени и LLM подсказками.

**Веб-приложение** (FastAPI + React) в `ai-helper-web/`, доступ через браузер.

Работает с ElevenLabs/Deepgram/Gemini (транскрипция) и OpenRouter (LLM). Поддерживает загрузку PDF документов (договоры, ВОР, сметы) как контекст для подсказок.

---

## Стек

- **Backend:** FastAPI + SQLAlchemy async + SQLite (dev) / PostgreSQL (prod)
- **Frontend:** React 19 + TypeScript + Vite + Zustand v5
- **Auth:** email + пароль, JWT (PyJWT), bcrypt
- **Realtime:** WebSocket для аудио/транскрипции/подсказок
- **Аудио:** Browser AudioWorklet → PCM 16kHz Int16 → WS binary frames

## Структура

```
ai-helper-web/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, LoggingMiddleware
│   │   ├── config.py            # Settings из .env (Pydantic)
│   │   ├── database.py          # SQLAlchemy async engine (aiosqlite)
│   │   ├── models/              # ORM: User, ApiKey, UserSettings, MeetingSession, SavedTranscription
│   │   ├── schemas/             # Pydantic: auth, meeting, settings
│   │   ├── auth/                # register, login, JWT, bcrypt (без passlib)
│   │   ├── api/                 # REST: admin, settings, documents, meetings
│   │   ├── ws/handler.py        # WebSocket /ws/meeting — ядро (аудио, транскрипция, LLM)
│   │   ├── services/            # SessionManager, AudioBridge
│   │   └── core/                # transcription, context, llm
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
└── start_dev.bat                # Запуск backend + frontend одной командой
```

## Запуск (dev)

```bash
# Вариант 1: через bat файл
ai-helper-web\start_dev.bat

# Вариант 2: вручную (два терминала)
# Terminal 1 — Backend:
cd ai-helper-web\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2 — Frontend:
cd ai-helper-web\frontend
npm run dev
```

## API

```
POST   /api/auth/register, /api/auth/login, GET /api/auth/me
POST   /api/documents/upload, DELETE /api/documents/{filename}
GET/PUT /api/settings
POST   /api/transcriptions/save, GET /api/transcriptions, GET .../download?token=<jwt>
GET    /api/admin/users, PUT .../users/{id}
CRUD   /api/admin/api-keys
WS     /ws/meeting?token=<jwt>
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

- **CORS:** `allow_origin_regex=r"^https?://localhost(:\d+)?$"` вместо списка origins. CORSMiddleware добавлен ПОСЛЕДНИМ через `add_middleware()` (LIFO → outermost)
- **bcrypt:** Используем напрямую (не passlib) — passlib несовместим с bcrypt>=5.0
- **API client:** `baseURL` включает `/api` prefix, endpoints без дублирования
- **Download:** Query token auth (`?token=jwt`) вместо Bearer header (для прямых ссылок)
- **Audio feedback:** Silent GainNode предотвращает проигрывание микрофона в колонки

## Тестовый пользователь

- email: `admin@test.com`, password: `admin123`, role: admin

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

## Git

- Коммиты на русском, кратко (1-2 предложения)
- Без приписок "Generated with Claude Code" и "Co-Authored-By"

---

## Known Issues

- ElevenLabs, Deepgram, Gemini и OpenRouter — платные API
- Gemini: НЕ true streaming, задержка ~5 сек
- venv общий (`.venv/` в корне), frontend node_modules в `ai-helper-web/frontend/`
