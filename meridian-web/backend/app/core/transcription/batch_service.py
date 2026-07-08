"""ElevenLabs Scribe v2 batch transcription service.

Post-meeting finalization with:
- Real speaker diarization (unavailable in realtime)
- Keyterm prompting for construction domain
- Word-level timestamps
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, List

import requests

from .models import (
    CommittedSegment, TranscriptWord, WordType,
    SegmentOrigin, UNKNOWN_SPEAKER,
)
from .service import BOOSTED_KEYWORDS

logger = logging.getLogger("meridian.batch")


class BatchTranscriptionService:
    """Post-meeting batch transcription via ElevenLabs Scribe v2 REST API."""

    def __init__(
        self,
        api_key: str,
        language_code: str = "ru",
        model_id: str = "scribe_v2",
    ):
        self.api_key = api_key
        self.language_code = language_code
        self.model_id = model_id
        self.base_url = "https://api.elevenlabs.io/v1/speech-to-text"
        self.session = requests.Session()
        self.session.headers.update({"xi-api-key": api_key})
        # ElevenLabs гео-блокирует РФ (IP прод-сервера) → egress через прокси в разрешённой стране.
        from ...config import get_settings
        _proxy = get_settings().elevenlabs_proxy_url
        if _proxy:
            self.session.proxies.update({"http": _proxy, "https": _proxy})

    async def transcribe(
        self,
        wav_bytes: bytes,
        *,
        diarize: bool = True,
        keyterms: Optional[List[str]] = None,
        request_timeout: Optional[float] = None,
    ) -> List[CommittedSegment]:
        """Run batch transcription. Returns CommittedSegments with real speaker IDs.

        Args:
            wav_bytes: WAV audio bytes
            diarize: Enable speaker diarization (mono recordings)
            keyterms: Domain-specific terms (max 100, 50 chars each)
            request_timeout: HTTP request timeout (seconds). None → прежний дефолт (300s) для
                production-финализации. Per-channel STT canary (Этап 19) передаёт короткий bounded
                таймаут, чтобы HTTP-запрос не жил дольше asyncio-таймаута.
        """
        terms = keyterms or BOOSTED_KEYWORDS
        return await asyncio.to_thread(
            self._transcribe_sync, wav_bytes, diarize, terms, request_timeout
        )

    def _transcribe_sync(
        self,
        wav_bytes: bytes,
        diarize: bool,
        keyterms: List[str],
        request_timeout: Optional[float] = None,
    ) -> List[CommittedSegment]:
        """Synchronous batch API call (run in thread)."""
        http_timeout = request_timeout if request_timeout is not None else 300
        files = [
            ("audio", ("meeting.wav", wav_bytes, "audio/wav")),
            ("model_id", (None, self.model_id)),
            ("language_code", (None, self.language_code)),
            ("diarize", (None, str(diarize).lower())),
            ("timestamps_granularity", (None, "word")),
        ]

        # Add keyterms (max 100)
        for term in keyterms[:100]:
            files.append(("keyterms", (None, term[:50])))

        try:
            response = self.session.post(
                self.base_url, files=files, timeout=http_timeout
            )
            response.raise_for_status()
            data = response.json()
            return self._parse_response(data)
        except requests.exceptions.HTTPError as e:
            # Этап 20: безопасная сводка вместо raw provider body (без ключей/headers/тела).
            from .provider_error_safety import safe_provider_error_summary
            logger.error("[Batch] HTTP error: %s", safe_provider_error_summary(e, provider="elevenlabs_batch"))
            raise
        except Exception as e:
            from .provider_error_safety import safe_provider_error_summary
            logger.error("[Batch] Error: %s", safe_provider_error_summary(e, provider="elevenlabs_batch"))
            raise

    def _parse_response(self, data: dict) -> List[CommittedSegment]:
        """Parse batch API response into CommittedSegments.

        Groups consecutive words by speaker_id to form segments.
        Batch API returns real speaker_id values (unlike realtime).
        """
        raw_words = data.get("words", [])

        if not raw_words:
            text = data.get("text", "")
            if text:
                return [CommittedSegment(
                    text=text,
                    origin=SegmentOrigin.BATCH_FINALIZED,
                    speaker_id=UNKNOWN_SPEAKER,
                )]
            return []

        segments: List[CommittedSegment] = []
        current_speaker: Optional[str] = None
        current_words: List[TranscriptWord] = []

        for wd in raw_words:
            word_type_str = wd.get("type", "word")
            try:
                word_type = WordType(word_type_str)
            except ValueError:
                word_type = WordType.WORD

            word = TranscriptWord(
                text=wd.get("text", ""),
                start=wd.get("start", 0.0),
                end=wd.get("end", 0.0),
                type=word_type,
                logprob=wd.get("logprob"),
            )

            speaker = wd.get("speaker_id") or UNKNOWN_SPEAKER

            # New speaker run → flush previous segment
            if speaker != current_speaker and current_words:
                segments.append(CommittedSegment(
                    words=current_words,
                    speaker_id=current_speaker or UNKNOWN_SPEAKER,
                    origin=SegmentOrigin.BATCH_FINALIZED,
                ))
                current_words = []

            current_speaker = speaker
            current_words.append(word)

        # Flush last segment
        if current_words:
            segments.append(CommittedSegment(
                words=current_words,
                speaker_id=current_speaker or UNKNOWN_SPEAKER,
                origin=SegmentOrigin.BATCH_FINALIZED,
            ))

        logger.info(
            f"[Batch] Parsed {len(segments)} segments from "
            f"{len(raw_words)} words"
        )
        return segments
