"""Batch transcription service using Deepgram prerecorded API (async).

Выход в том же формате, что у ElevenLabs-сервиса ({text, words}), чтобы перевод,
протокол и слияние во встречу работали без различий по провайдеру.
"""

import asyncio
import mimetypes
import time
import logging
import requests
from typing import Optional, Dict, Any

from ..transcription.deepgram_streaming_service import IMPORTANT_KEYTERMS
from .transcription_service import MAX_RETRIES, RETRY_BACKOFF, RETRYABLE_STATUSES

logger = logging.getLogger(__name__)


class DeepgramBatchTranscriptionService:
    PARAMS = {
        "model": "nova-3",
        "language": "ru",
        "diarize": "true",
        "punctuate": "true",
        "smart_format": "true",
    }

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def transcribe(self, file_path: str, timeout: int = 600) -> Optional[Dict[str, Any]]:
        """Transcribe audio file. Returns {text, words} or None."""
        return await asyncio.to_thread(self._transcribe_sync, file_path, timeout)

    def _transcribe_sync(self, file_path: str, timeout: int) -> Optional[Dict[str, Any]]:
        try:
            from ...config import get_settings
            url = get_settings().deepgram_batch_url
            params = list(self.PARAMS.items()) + [("keyterm", t) for t in IMPORTANT_KEYTERMS]
            content_type = mimetypes.guess_type(file_path)[0] or "audio/*"
            headers = {"Authorization": f"Token {self.api_key}", "Content-Type": content_type}

            response = None
            for attempt in range(MAX_RETRIES):
                try:
                    with open(file_path, "rb") as audio_file:
                        response = requests.post(
                            url,
                            params=params,
                            headers=headers,
                            data=audio_file,
                            timeout=timeout,
                        )
                    if response.status_code not in RETRYABLE_STATUSES:
                        break
                    logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES}: status {response.status_code}")
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES}: {type(e).__name__}")
                    response = None

                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[attempt])

            if response and response.status_code == 200:
                return self._parse_response(response.json())

            status = response.status_code if response else "no response"
            text = response.text[:500] if response else ""
            logger.error(f"Deepgram API error: {status} - {text}")
            return None

        except Exception as e:
            logger.error(f"Transcription error: {type(e).__name__}: {e}")
            return None

    def _parse_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        channels = (result.get("results") or {}).get("channels") or [{}]
        alt = (channels[0].get("alternatives") or [{}])[0]
        transcription = {"text": alt.get("transcript", ""), "words": []}

        for word in alt.get("words", []):
            speaker = word.get("speaker")
            transcription["words"].append({
                "text": word.get("punctuated_word") or word.get("word", ""),
                "start": word.get("start", 0),
                "end": word.get("end", 0),
                # как у ElevenLabs ('Speaker_speaker_0') — единый вид id спикеров в батчах
                "speaker_id": f"Speaker_speaker_{speaker}" if speaker is not None else "Speaker_1",
            })

        return transcription
