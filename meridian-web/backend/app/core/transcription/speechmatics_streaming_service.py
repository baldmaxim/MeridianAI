"""Speechmatics RT API v2 streaming transcription service via WebSocket."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, Optional

import websockets

from .models import TranscriptSegment

logger = logging.getLogger("meridian.speechmatics")

SPEECHMATICS_WS_URL = "wss://eu2.rt.speechmatics.com/v2"

ADDITIONAL_VOCAB = [
    "СУ-10", "КС-2", "КС-3", "М-29", "BIM", "Revit",
    "генподрядчик", "субподрядчик", "заказчик", "застройщик",
    "смета", "аванс", "неустойка", "гарантия", "СМР",
    {"content": "ОСП", "sounds_like": ["о эс пэ"]},
    {"content": "ПСД", "sounds_like": ["пэ эс дэ"]},
]


class SpeechmaticsStreamingTranscriptionService:
    """Streaming transcription using Speechmatics RT API v2 with diarization."""

    def __init__(self, api_key: str, audio_queue: asyncio.Queue,
                 message_callback: Callable,
                 sample_rate: int = 16000):
        self.api_key = api_key
        self.audio_queue = audio_queue
        self.message_callback = message_callback
        self.sample_rate = sample_rate

        self.is_running = False
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._audio_chunks_sent = 0

    def _build_start_recognition(self) -> dict:
        return {
            "message": "StartRecognition",
            "audio_format": {
                "type": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": self.sample_rate,
            },
            "transcription_config": {
                "language": "ru",
                "operating_point": "enhanced",
                "max_delay": 3.5,
                "max_delay_mode": "flexible",
                "enable_partials": True,
                "enable_entities": True,
                "diarization": "speaker",
                "speaker_diarization_config": {
                    "max_speakers": 3,
                    "prefer_current_speaker": True,
                    "speaker_sensitivity": 0.35,
                },
                "punctuation_overrides": {
                    "permitted_marks": ["all"],
                    "sensitivity": 0.55,
                },
                "conversation_config": {
                    "end_of_utterance_silence_trigger": 1.1,
                },
                "additional_vocab": ADDITIONAL_VOCAB,
            },
        }

    async def connect(self) -> bool:
        try:
            headers = [("Authorization", f"Bearer {self.api_key}")]
            logger.info("Connecting to %s", SPEECHMATICS_WS_URL)
            self.ws = await websockets.connect(
                SPEECHMATICS_WS_URL, additional_headers=headers,
            )
            # Send StartRecognition config
            await self.ws.send(json.dumps(self._build_start_recognition()))
            logger.info("StartRecognition sent")

            # Wait for RecognitionStarted (skip Info messages)
            deadline = asyncio.get_event_loop().time() + 10
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    logger.error("Timeout waiting for RecognitionStarted")
                    return False
                response = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
                data = json.loads(response)
                msg = data.get("message", "")
                if msg == "RecognitionStarted":
                    logger.info("RecognitionStarted OK")
                    self._audio_chunks_sent = 0
                    return True
                elif msg == "Info":
                    logger.info("Info: %s", data.get("reason", ""))
                    continue
                else:
                    logger.error("Unexpected response: %s", data)
                    return False
        except Exception as e:
            logger.error("Connection error: %s", e)
            return False

    async def disconnect(self):
        if self.ws:
            try:
                await self.ws.send(json.dumps({
                    "message": "EndOfStream",
                    "last_seq_no": self._audio_chunks_sent,
                }))
                try:
                    await asyncio.wait_for(self.ws.recv(), timeout=5)
                except (asyncio.TimeoutError, Exception):
                    pass
                await self.ws.close()
            except Exception:
                pass
            finally:
                self.ws = None

    async def run(self):
        self.is_running = True
        reconnect_delay = 1

        while self.is_running:
            try:
                if not await self.connect():
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)
                    continue

                reconnect_delay = 1
                await asyncio.gather(
                    self._send_audio_loop(),
                    self._receive_loop(),
                )
            except websockets.exceptions.ConnectionClosed as e:
                if self.is_running:
                    logger.warning("Connection closed (%s), reconnecting...", e)
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)
            except Exception as e:
                logger.error("Run error: %s", e, exc_info=True)
                if self.is_running:
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)

    async def _send_audio_loop(self):
        logger.info("Audio send loop started")
        chunks_sent = 0
        while self.is_running and self.ws:
            try:
                chunk = await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
                if chunk:
                    timestamp, audio_data = chunk
                    await self.ws.send(audio_data)
                    self._audio_chunks_sent += 1
                    chunks_sent += 1
                    if chunks_sent <= 5 or chunks_sent % 100 == 0:
                        logger.info("Audio chunk #%d sent (%d bytes)", chunks_sent, len(audio_data))
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Send error: %s", e)
                break
        logger.info("Audio send loop ended (sent %d chunks)", chunks_sent)

    async def _receive_loop(self):
        logger.info("Receive loop started")
        msg_count = 0
        async for message in self.ws:
            if not self.is_running:
                break
            try:
                data = json.loads(message)
                msg_type = data.get("message", "")
                msg_count += 1

                if msg_type == "AddTranscript":
                    metadata = data.get("metadata", {})
                    logger.info("AddTranscript: '%s'", metadata.get("transcript", "")[:100])
                    self._handle_transcript(data)
                elif msg_type == "AddPartialTranscript":
                    metadata = data.get("metadata", {})
                    text = metadata.get("transcript", "")
                    if text.strip():
                        logger.debug("Partial: '%s'", text[:80])
                    self._handle_partial(data)
                elif msg_type == "EndOfTranscript":
                    logger.info("EndOfTranscript received")
                    break
                elif msg_type == "Error":
                    logger.error("Server error: %s", data)
                elif msg_type == "AudioAdded":
                    if msg_count <= 3:
                        logger.debug("AudioAdded seq_no=%s", data.get("seq_no"))
                elif msg_type == "Info":
                    logger.info("Info: %s", data.get("reason", ""))
                else:
                    logger.warning("Unknown message type: %s", msg_type)
            except Exception as e:
                logger.error("Receive error: %s", e, exc_info=True)
        logger.info("Receive loop ended (%d messages received)", msg_count)

    def _handle_partial(self, data: dict):
        """Handle partial transcript — UI preview only."""
        metadata = data.get("metadata", {})
        transcript = metadata.get("transcript", "").strip()
        if not transcript:
            return
        segment = TranscriptSegment(
            speaker="...",
            text=transcript,
            start_time=metadata.get("start_time", 0.0),
            end_time=metadata.get("end_time", 0.0),
            timestamp=datetime.now(),
        )
        self.message_callback(segment, is_partial=True)

    def _handle_transcript(self, data: dict):
        """Handle final transcript — single utterance, dominant speaker."""
        metadata = data.get("metadata", {})
        transcript = metadata.get("transcript", "").strip()
        if not transcript:
            return

        results = data.get("results", [])

        # Dominant speaker: count words per speaker, pick the most frequent
        speaker_counts: dict[str, int] = {}
        for word in results:
            if word.get("type") != "word":
                continue
            alts = word.get("alternatives", [])
            if not alts:
                continue
            spk = alts[0].get("speaker")
            label = f"SM_{spk}" if spk is not None else "Unknown"
            speaker_counts[label] = speaker_counts.get(label, 0) + 1

        speaker = max(speaker_counts, key=speaker_counts.get) if speaker_counts else "Unknown"

        # Timing from results
        start_time = results[0].get("start_time", 0.0) if results else 0.0
        end_time = results[-1].get("end_time", 0.0) if results else 0.0

        # Average confidence
        confidences = []
        for w in results:
            alts = w.get("alternatives", [])
            if alts and "confidence" in alts[0]:
                confidences.append(alts[0]["confidence"])
        avg_confidence = sum(confidences) / len(confidences) if confidences else None

        segment = TranscriptSegment(
            speaker=speaker,
            text=transcript,
            start_time=start_time,
            end_time=end_time,
            timestamp=datetime.now(),
            confidence=avg_confidence,
        )
        logger.info("Emitting 1 segment: speaker=%s, len=%d", speaker, len(transcript))
        self.message_callback(segment, is_partial=False)

    def stop(self):
        self.is_running = False
