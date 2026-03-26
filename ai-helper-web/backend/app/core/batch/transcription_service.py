"""Batch transcription service using ElevenLabs API (async)."""

import asyncio
import time
import logging
import requests
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class BatchTranscriptionService:
    API_URL = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def transcribe(self, file_path: str, timeout: int = 600) -> Optional[Dict[str, Any]]:
        """Transcribe audio file. Returns {text, words} or None."""
        return await asyncio.to_thread(self._transcribe_sync, file_path, timeout)

    def _transcribe_sync(self, file_path: str, timeout: int) -> Optional[Dict[str, Any]]:
        try:
            headers = {"xi-api-key": self.api_key}
            data = {
                "model_id": "scribe_v2",
                "diarize": "true",
                "timestamps_granularity": "word",
            }

            response = None
            for attempt in range(MAX_RETRIES):
                try:
                    with open(file_path, "rb") as audio_file:
                        files = {"file": (Path(file_path).name, audio_file)}
                        response = requests.post(
                            self.API_URL,
                            headers=headers,
                            data=data,
                            files=files,
                            timeout=timeout,
                        )
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

    def _parse_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        transcription = {"text": result.get("text", ""), "words": []}

        for word in result.get("words", []):
            speaker = word.get("speaker_id", word.get("speaker", ""))
            transcription["words"].append({
                "text": word.get("text", ""),
                "start": word.get("start", 0),
                "end": word.get("end", 0),
                "speaker_id": f"Speaker_{speaker}" if speaker else "Speaker_1",
            })

        return transcription
