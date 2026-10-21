"""Batch transcription service using GigaAM (внешний HTTP-сервис, async-обёртка).

Сервис доступен только через SSH-туннель, поэтому токен выдаётся без авторизации
(GET /api/session) и берётся на каждое задание. Выход в том же формате, что у
Deepgram/ElevenLabs ({text, words}), чтобы перевод, протокол и слияние во встречу
работали без различий по провайдеру.
"""

import asyncio
import logging
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from .transcription_service import MAX_RETRIES, RETRY_BACKOFF, RETRYABLE_STATUSES

logger = logging.getLogger(__name__)

MODEL = "gigaam-v3"
POLL_INTERVAL = 3  # секунд между опросами статуса задания
HTTP_TIMEOUT = 30  # секунд на короткие запросы (session, poll)
UPLOAD_TIMEOUT = 600  # секунд на загрузку файла
_SPEAKER_NUM = re.compile(r"(\d+)\s*$")


class GigaAMBatchTranscriptionService:
    def __init__(self, base_url: str, max_speakers: Optional[int] = None):
        self.base_url = base_url.rstrip("/")
        # Верхняя граница для диаризации (pyannote): без неё дробит быстрые перебивки
        self.max_speakers = max_speakers
        # Сервис принимает только Host 127.0.0.1/localhost (защита от DNS rebinding),
        # а на проде он доступен по имени контейнера туннеля
        self.host_header = {"Host": f"127.0.0.1:{urlparse(self.base_url).port or 80}"}

    async def transcribe(self, file_path: str, timeout: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Transcribe audio file. Returns {text, words} or None."""
        if timeout is None:
            from ...config import get_settings
            timeout = get_settings().gigaam_timeout_seconds
        return await asyncio.to_thread(self._transcribe_sync, file_path, timeout)

    def _transcribe_sync(self, file_path: str, timeout: int) -> Optional[Dict[str, Any]]:
        deadline = time.monotonic() + timeout
        try:
            token = self._get_token()
            if not token:
                return None
            headers = {**self.host_header, "Authorization": f"Bearer {token}"}

            job_id = self._submit(file_path, headers)
            if not job_id:
                return None

            result = self._wait_result(job_id, headers, deadline)
            if result is None:
                return None
            return self._parse_result(result)

        except Exception as e:
            logger.error(f"GigaAM transcription error: {type(e).__name__}: {e}")
            return None

    def _get_token(self) -> Optional[str]:
        """Токен сессии (без авторизации — доступ только через туннель)."""
        try:
            response = requests.get(f"{self.base_url}/api/session", headers=self.host_header, timeout=HTTP_TIMEOUT)
            if response.status_code == 200:
                return response.json().get("token") or None
            logger.error(f"GigaAM session error: {response.status_code}")
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.error(f"GigaAM session unavailable: {type(e).__name__}")
        return None

    def _submit(self, file_path: str, headers: Dict[str, str]) -> Optional[str]:
        """Создать задание; на 429/503/сетевых ошибках повторять с backoff."""
        form = {"model": MODEL, "diarize": "true"}
        if self.max_speakers:
            form["max_speakers"] = str(self.max_speakers)
        response = None
        for attempt in range(MAX_RETRIES):
            try:
                with open(file_path, "rb") as audio_file:
                    response = requests.post(
                        f"{self.base_url}/api/jobs",
                        headers=headers,
                        files={"file": audio_file},
                        data=form,
                        timeout=UPLOAD_TIMEOUT,
                    )
                if response.status_code not in RETRYABLE_STATUSES:
                    break
                logger.warning(f"GigaAM retry {attempt + 1}/{MAX_RETRIES}: status {response.status_code}")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                logger.warning(f"GigaAM retry {attempt + 1}/{MAX_RETRIES}: {type(e).__name__}")
                response = None

            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])

        if response is not None and response.status_code in (200, 201, 202):
            job_id = response.json().get("id")
            if job_id:
                logger.info(f"GigaAM job {job_id}: создано")
                return str(job_id)

        status = response.status_code if response is not None else "no response"
        logger.error(f"GigaAM job create error: {status}")
        return None

    def _wait_result(self, job_id: str, headers: Dict[str, str], deadline: float) -> Optional[Dict[str, Any]]:
        """Опрашивать задание до done/failed или дедлайна. Сетевые сбои опроса не фатальны."""
        while True:
            try:
                response = requests.get(
                    f"{self.base_url}/api/jobs/{job_id}", headers=headers, timeout=HTTP_TIMEOUT
                )
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status")
                    if status == "done":
                        logger.info(f"GigaAM job {job_id}: готово")
                        return data.get("result") or {}
                    if status == "failed":
                        logger.error(f"GigaAM job {job_id}: failed ({data.get('error')})")
                        return None
                else:
                    logger.warning(f"GigaAM job {job_id}: poll status {response.status_code}")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                logger.warning(f"GigaAM job {job_id}: poll {type(e).__name__}")

            if time.monotonic() + POLL_INTERVAL > deadline:
                logger.error(f"GigaAM job {job_id}: таймаут ожидания")
                return None
            time.sleep(POLL_INTERVAL)

    @staticmethod
    def _normalize_speaker(speaker_id: Any) -> str:
        """'Speaker_SPEAKER_03' → 'Speaker_speaker_3' (как у Deepgram/ElevenLabs)."""
        match = _SPEAKER_NUM.search(str(speaker_id)) if speaker_id else None
        return f"Speaker_speaker_{int(match.group(1))}" if match else "Speaker_1"

    def _parse_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        transcription = {"text": result.get("text") or "", "words": []}
        for word in result.get("words") or []:
            transcription["words"].append({
                "text": word.get("text", ""),
                "start": word.get("start", 0),
                "end": word.get("end", 0),
                "speaker_id": self._normalize_speaker(word.get("speaker_id")),
            })
        return transcription
