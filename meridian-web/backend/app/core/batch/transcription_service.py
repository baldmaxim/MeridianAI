"""Batch transcription service using ElevenLabs API (async)."""

import asyncio
import time
import logging
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Ограничения ElevenLabs на keyterms (scribe_v3): до 1000 штук, короче 50 символов, до 5 слов.
KEYTERMS_LIMIT = 1000
KEYTERMS_MAX_CHARS = 49
KEYTERMS_MAX_WORDS = 5


def stt_language_settings() -> tuple[str, List[str]]:
    """(основной язык, дополнительные языки) из настроек живого распознавания.

    Те же ELEVENLABS_LIVE_LANGUAGE / ELEVENLABS_LIVE_SECONDARY_LANGUAGES, что у live: смешанные
    русско-турецкие встречи распознаются одинаково и вживую, и при уточнении записи.
    """
    from ...config import get_settings
    from ..transcription.elevenlabs_live_protocol import LiveOptions
    options = LiveOptions.from_settings(get_settings())
    return options.language, list(options.secondary_languages)


class BatchTranscriptionService:
    API_URL = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(self, api_key: str, max_speakers: Optional[int] = None,
                 keyterms: Optional[List[str]] = None,
                 language_code: Optional[str] = None,
                 secondary_language_codes: Optional[List[str]] = None):
        self.api_key = api_key
        # None → из настроек (ru + tr). Пустая строка / пустой список — не передавать (автоопределение).
        default_language, default_secondary = stt_language_settings()
        self.language_code = default_language if language_code is None else language_code
        self.secondary_language_codes = (
            default_secondary if secondary_language_codes is None else list(secondary_language_codes))
        # Термины предметной области: подсказка модели (смещение к нужному написанию)
        self.keyterms = keyterms or []
        # Число говорящих, если пользователь его знает (num_speakers); None — авто
        self.max_speakers = max_speakers

    async def transcribe(self, file_path: str, timeout: int = 600) -> Optional[Dict[str, Any]]:
        """Transcribe audio file. Returns {text, words} or None."""
        return await asyncio.to_thread(self._transcribe_sync, file_path, timeout)

    def _transcribe_sync(self, file_path: str, timeout: int) -> Optional[Dict[str, Any]]:
        try:
            from ...config import get_settings
            proxy = get_settings().elevenlabs_proxy_url
            proxies = {"http": proxy, "https": proxy} if proxy else None

            headers = {"xi-api-key": self.api_key}
            data = {
                "model_id": "scribe_v3",
                "diarize": "true",
                "timestamps_granularity": "word",
                # numbers_format=digits не ставим: стенд 17.11.2026 (5 записей) — с ним чисел цифрами
                # стало вдвое меньше («сто девяносто восемь» вместо 198), по умолчанию v3 пишет цифры
            }
            if self.max_speakers:
                data["num_speakers"] = str(self.max_speakers)
            if self.language_code:
                data["language_code"] = self.language_code
                if self.secondary_language_codes:
                    # повторяющееся поле формы (как keyterms)
                    data["secondary_language_codes"] = list(self.secondary_language_codes)
            if self.keyterms:
                # requests кладёт список в multipart повторяющимися полями keyterms
                data["keyterms"] = list(self.keyterms)

            response = None
            attempt = -1
            while attempt < MAX_RETRIES - 1:
                attempt += 1
                try:
                    with open(file_path, "rb") as audio_file:
                        files = {"file": (Path(file_path).name, audio_file)}
                        response = requests.post(
                            self.API_URL,
                            headers=headers,
                            data=data,
                            files=files,
                            timeout=timeout,
                            proxies=proxies,
                        )
                    if "keyterms" in data and self._is_keyterms_rejection(response):
                        # Подсказки не принялись — один раз пробуем без них, а не роняем распознавание
                        logger.warning(f"ElevenLabs отклонил keyterms ({response.status_code}): "
                                       f"{response.text[:300]}; повтор без них")
                        del data["keyterms"]
                        attempt -= 1  # повтор без keyterms не тратит попытку
                        continue
                    if "secondary_language_codes" in data and self._is_secondary_languages_rejection(response):
                        # Второй язык не принялся — один раз пробуем без него, а не роняем распознавание
                        logger.warning(f"ElevenLabs отклонил secondary_language_codes ({response.status_code}): "
                                       f"{response.text[:300]}; повтор без них")
                        del data["secondary_language_codes"]
                        attempt -= 1
                        continue
                    if response.status_code not in RETRYABLE_STATUSES:
                        break
                    logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES}: status {response.status_code}")
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES}: {e}")
                    response = None

                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[attempt])

            if response and response.status_code == 200:
                result = response.json()
                return self._parse_response(result)

            status = response.status_code if response else "no response"
            text = response.text[:500] if response else ""
            logger.error(f"ElevenLabs API error: {status} - {text}")
            return None

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None

    @staticmethod
    def _is_keyterms_rejection(response) -> bool:
        """4xx (кроме 429), в тексте ошибки упомянуты keyterms."""
        status = response.status_code
        if not (400 <= status < 500) or status == 429:
            return False
        return "keyterm" in (response.text or "").lower()

    @staticmethod
    def _is_secondary_languages_rejection(response) -> bool:
        """4xx (кроме 429), в тексте ошибки упомянут secondary-язык."""
        status = response.status_code
        if not (400 <= status < 500) or status == 429:
            return False
        return "secondary" in (response.text or "").lower()

    def _parse_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        transcription = {"text": result.get("text", ""), "words": []}
        language = result.get("language_code")
        if isinstance(language, str) and language:
            transcription["language_code"] = language  # язык ответа (основной в файле)

        for word in result.get("words", []):
            speaker = word.get("speaker_id", word.get("speaker", ""))
            transcription["words"].append({
                "text": word.get("text", ""),
                "start": word.get("start", 0),
                "end": word.get("end", 0),
                "speaker_id": f"Speaker_{speaker}" if speaker else "Speaker_1",
            })

        return transcription
