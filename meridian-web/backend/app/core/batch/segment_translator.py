"""Перевод иноязычных реплик транскрипта на русский (OpenRouter).

Распознавание (Scribe v2) само определяет язык и сохраняет речь как есть — коллеги из
Турции переключаются на свой язык по ходу встречи, и такие реплики остаются турецкими.
Здесь они переводятся на русский ПОРЕПЛИЧНО, оригинал не заменяется: в переговорах важно
сверить формулировку цены или срока с тем, что реально прозвучало.

Перевод идёт по репликам, а не по словам: word-level тайминги из transcription_json
держат перемотку плеера и нарезку фрагментов, их трогать нельзя.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("meridian.batch")

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Реплик в одном запросе: длинная встреча не должна упираться в лимит ответа модели.
CHUNK_SIZE = 60
# Доля кириллицы, ниже которой реплика считается иноязычной.
CYRILLIC_RATIO = 0.5

_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

SYSTEM_PROMPT = """Ты — переводчик деловых переговоров в строительной сфере.
Переводишь реплики транскрипта на русский язык.

ПРАВИЛА:
- Переводи только смысл сказанного. Ничего не добавляй и не додумывай.
- Сохраняй числа, суммы, единицы измерения, даты и названия компаний как в оригинале.
- Термины стройки переводи профессионально (смета, ВОР, аванс, объём работ, гарантия).
- Обрывы и оговорки оставляй обрывами — не «дописывай» фразу за говорящего.
- Если реплика уже на русском — верни её без изменений.
- Если реплика неразборчива и смысла нет — верни пустую строку.
- Никаких пояснений и комментариев: только перевод."""


def needs_translation(text: str) -> bool:
    """Реплика иноязычная? Считаем по доле кириллицы среди букв.

    Дешевле и надёжнее внешнего детектора языка: нам не нужно знать, ЧТО за язык —
    достаточно понять, что это не русский.
    """
    letters = _LETTER.findall(text or "")
    if not letters:
        return False
    cyr = len(_CYRILLIC.findall(text))
    return (cyr / len(letters)) < CYRILLIC_RATIO


class SegmentTranslator:
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "google/gemini-3-flash-preview"):
        self.api_key = api_key
        self.model = model

    async def translate(self, texts: List[str], timeout: int = 180) -> Dict[int, str]:
        """Перевести иноязычные реплики. Возвращает {индекс в texts: перевод}.

        Русские реплики пропускаются и в ответе не появляются. Сбой перевода не
        обязан ронять задачу: при ошибке вернётся то, что успело перевестись.
        """
        targets = [i for i, t in enumerate(texts) if needs_translation(t)]
        if not targets:
            return {}
        logger.info("[Translate] иноязычных реплик: %d из %d", len(targets), len(texts))

        out: Dict[int, str] = {}
        for pos in range(0, len(targets), CHUNK_SIZE):
            chunk = targets[pos:pos + CHUNK_SIZE]
            part = await asyncio.to_thread(
                self._translate_chunk, [(i, texts[i]) for i in chunk], timeout
            )
            out.update(part)
        logger.info("[Translate] переведено реплик: %d", len(out))
        return out

    def _translate_chunk(self, items: List[tuple[int, str]], timeout: int) -> Dict[int, str]:
        numbered = "\n".join(f"{i}. {text}" for i, text in items)
        user_prompt = (
            "Переведи реплики на русский. Ответ — ОДИН JSON-объект, где ключ — номер "
            "реплики строкой, значение — перевод. Без markdown, без пояснений.\n"
            'Пример ответа: {"0": "Цена слишком высокая", "3": "Согласны на аванс"}\n\n'
            f"РЕПЛИКИ:\n{numbered}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/meridian",
            "X-Title": "Meridian - AI Negotiation Helper",
        }
        try:
            response = self._request_with_retry(headers, payload, timeout)
            if not response or response.status_code != 200:
                if response:
                    logger.error("[Translate] OpenRouter %s: %s",
                                 response.status_code, response.text[:200])
                return {}
            content = (response.json().get("choices") or [{}])[0].get("message", {}).get("content")
            return self._parse(content, {i for i, _ in items})
        except Exception as e:
            logger.error("[Translate] ошибка перевода: %s", e)
            return {}

    @staticmethod
    def _parse(content: Optional[str], allowed: set[int]) -> Dict[int, str]:
        """Разобрать ответ модели. Лишние/битые ключи молча отбрасываем."""
        if not content:
            return {}
        raw = content.strip()
        # Модель иногда всё же оборачивает JSON в ```json ... ```
        fenced = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
        if fenced:
            raw = fenced.group(1).strip()
        try:
            data: Any = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("[Translate] невалидный JSON от модели: %s", e)
            return {}
        if not isinstance(data, dict):
            return {}
        out: Dict[int, str] = {}
        for k, v in data.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            if idx in allowed and isinstance(v, str) and v.strip():
                out[idx] = v.strip()
        return out

    def _request_with_retry(self, headers: dict, payload: dict, timeout: int):
        # OpenRouter гео-блокирует РФ (IP прод-сервера) → тот же egress-прокси, что у протокола.
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
                logger.warning("[Translate] retry %d/%d: status %s",
                               attempt + 1, MAX_RETRIES, response.status_code)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                logger.warning("[Translate] retry %d/%d: %s", attempt + 1, MAX_RETRIES, e)
            if attempt < MAX_RETRIES - 1:
                import time
                time.sleep(RETRY_BACKOFF[attempt])
        return None
