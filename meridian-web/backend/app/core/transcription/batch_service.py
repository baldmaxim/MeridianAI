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

    async def transcribe(
        self,
        wav_bytes: bytes,
        *,
        diarize: bool = True,
        keyterms: Optional[List[str]] = None,
    ) -> List[CommittedSegment]:
        """Run batch transcription. Returns CommittedSegments with real speaker IDs.

        Args:
            wav_bytes: WAV audio bytes
            diarize: Enable speaker diarization (mono recordings)
            keyterms: Domain-specific terms (max 100, 50 chars each)
        """
        terms = keyterms or BOOSTED_KEYWORDS
        return await asyncio.to_thread(
            self._transcribe_sync, wav_bytes, diarize, terms
        )

    def _transcribe_sync(
        self,
        wav_bytes: bytes,
        diarize: bool,
        keyterms: List[str],
    ) -> List[CommittedSegment]:
        """Synchronous batch API call (run in thread)."""
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
                self.base_url, files=files, timeout=300
            )
            response.raise_for_status()
            data = response.json()
            return self._parse_response(data)
        except requests.exceptions.HTTPError as e:
            logger.error(f"[Batch] HTTP error: {e} - {e.response.text if e.response else ''}")
            raise
        except Exception as e:
            logger.error(f"[Batch] Error: {e}")
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
