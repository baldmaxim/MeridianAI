"""Protocol generation service using OpenRouter API (async)."""

import asyncio
import time
import logging
import requests
from typing import Optional, Dict, Any

from .utils import format_utterances

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class ProtocolGenerator:
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    SYSTEM_PROMPT = """Ты — корпоративный секретарь и аналитик протокола.
Работаешь ТОЛЬКО по транскрипту ниже.

ЖЁСТКИЕ ПРАВИЛА:
- Не выдумывай факты, даты, имена, решения, сроки.
- Если информации нет в тексте — пиши: "не указано".
- Если есть неопределённость/спор/противоречие — явно зафиксируй это.
- Таймкоды используй только те, что есть в репликах.
- Короткие цитаты: до 20 слов, без редактирования.
Стиль: деловой, нейтральный, русский язык."""

    TASK_PROMPT_TEMPLATE = """Ниже транскрипт встречи репликами. Формат реплик:
[ТАЙМКОД_НАЧАЛА\u2013ТАЙМКОД_КОНЦА] Speaker_X: текст

СФОРМИРУЙ ДВА БЛОКА В ОТВЕТЕ:

БЛОК 1 (Markdown): официальный протокол со строгими заголовками:
## 1. Общая информация
- Тип встречи: ...
- Тема: ...
- Дата: ...
- Длительность: ...
(Если не указано в тексте — "не указано")

## 2. Участники
- Speaker_1 — ...
(Не придумывай имена/роли; если в тексте нет — "не указано")

## 3. Краткое резюме (5\u201310 пунктов)
Каждый пункт: факт + (таймкод)

## 4. Обсуждаемые вопросы
Для каждого: суть, кто говорил, позиции, таймкоды

## 5. Принятые решения
Только явно озвученные решения.
Для каждого: формулировка, статус (принято/предварительно/отложено), таймкод начала обсуждения.

## 6. Задачи и договорённости
Markdown-таблица:
| Задача | Ответственный | Срок | Основание (таймкод) |
Если задач нет — таблица с одной строкой "\u2014".

## 7. Риски/спорные моменты
## 8. Незакрытые вопросы
## 9. Ключевые цитаты (опционально)

БЛОК 2 (JSON): СРАЗУ ПОСЛЕ Markdown выведи один кодовый блок ```json ... ```
JSON должен быть ВАЛИДНЫМ (без комментариев/висячих запятых) и соответствовать схеме:
{{
  "meeting": {{"type": "...", "topic": "...", "date": "...", "duration": "..."}},
  "participants": [{{"id":"Speaker_1","name":"не указано","role":"не указано"}}],
  "summary_points": [{{"text":"...","timecodes":["MM:SS"],"speakers":["Speaker_1"]}}],
  "decisions": [{{"text":"...","status":"принято|предварительно|отложено|не принято","timecode":"MM:SS","speakers":["Speaker_1"]}}],
  "action_items": [{{"task":"...","owner":"Speaker_2","due":"не указано","timecode":"MM:SS"}}],
  "risks": [{{"text":"...","timecodes":["MM:SS"],"speakers":["Speaker_1"]}}],
  "open_questions": [{{"text":"...","timecodes":["MM:SS"],"speakers":["Speaker_1"]}}],
  "key_quotes": [{{"quote":"...","speaker":"Speaker_1","timecode":"MM:SS"}}],
  "uncertainties": [{{"text":"...","timecodes":["MM:SS"],"speakers":["Speaker_1"]}}]
}}
Если раздел пуст — [].
Если значение неизвестно — "не указано".

ТРАНСКРИПТ:
{utterances}"""

    def __init__(self, api_key: str, model: str = "google/gemini-3-flash-preview"):
        self.api_key = api_key
        self.model = model

    async def generate(self, transcription_data: Dict[str, Any], timeout: int = 180) -> Optional[str]:
        return await asyncio.to_thread(self._generate_sync, transcription_data, timeout)

    def _generate_sync(self, transcription_data: Dict[str, Any], timeout: int) -> Optional[str]:
        try:
            utterances = format_utterances(transcription_data)
            task_prompt = self.TASK_PROMPT_TEMPLATE.format(utterances=utterances)

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": task_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 16384,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                # OpenRouter app-identification (как в live-клиенте, ASCII-only).
                "HTTP-Referer": "https://github.com/meridian",
                "X-Title": "Meridian - AI Negotiation Helper",
            }

            response = self._request_with_retry(headers, payload, timeout)

            if response and response.status_code == 200:
                result = response.json()
                if "choices" in result and result["choices"]:
                    return result["choices"][0]["message"]["content"]
            elif response:
                logger.error(f"OpenRouter API error: {response.status_code} {response.text[:200]}")

            return None

        except Exception as e:
            logger.error(f"Protocol generation error: {e}")
            return None

    def _request_with_retry(self, headers: dict, payload: dict, timeout: int):
        from ...config import get_settings
        proxy = get_settings().openrouter_proxy_url
        proxies = {"http": proxy, "https": proxy} if proxy else None
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(
                    self.API_URL, headers=headers, json=payload, timeout=timeout,
                    proxies=proxies,
                )
                if response.status_code not in RETRYABLE_STATUSES:
                    return response
                logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES}: status {response.status_code}")
            except requests.exceptions.Timeout:
                logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES}: timeout")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES}: connection error")

            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])

        return None
