# MERIDIAN — AI-ассистент для переговоров

Веб-приложение для помощи в переговорах в строительной сфере: транскрипция в реальном времени + LLM подсказки.

## Стек

- **Backend:** FastAPI + SQLAlchemy async + SQLite/PostgreSQL
- **Frontend:** React 19 + TypeScript + Vite + Zustand
- **STT:** ElevenLabs / Deepgram / Gemini (WebSocket streaming)
- **LLM:** OpenRouter

## Быстрый старт

```bash
# Запуск (backend + frontend)
meridian-web\start_dev.bat
```

Или вручную:

```bash
# Backend (терминал 1)
cd meridian-web\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (терминал 2)
cd meridian-web\frontend
npm run dev
```

## Конфигурация

Настройки в `meridian-web/backend/.env` — создать по шаблону `.env.example`.

## Тестовый доступ

- email: `admin@test.com`
- password: `admin123`
