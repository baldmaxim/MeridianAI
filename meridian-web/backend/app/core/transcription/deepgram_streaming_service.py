"""Deepgram streaming transcription service via WebSocket.

Adapted for web: uses asyncio.Queue instead of threading queue.
"""

import asyncio
import json
import time
import urllib.parse
from datetime import datetime
from typing import Callable, List, Optional

import websockets

from .models import TranscriptSegment

# Domain-specific keyterms for Nova-3
IMPORTANT_KEYTERMS = [
    "КС-2", "КС-3", "КС-6", "КС-11", "СУ-10", "ПСД",
    "генподрядчик", "субподрядчик", "заказчик", "застройщик",
    "смета", "аванс", "неустойка", "гарантия",
    "СМР", "монтаж", "демонтаж",
]


class DeepgramStreamingTranscriptionService:
    """Streaming transcription using Deepgram WebSocket API with diarization."""

    def __init__(self, api_key: str, audio_queue: asyncio.Queue,
                 message_callback: Callable,
                 model: str = "nova-3", language: str = "ru",
                 sample_rate: int = 16000, diarization: bool = True):
        self.api_key = api_key
        self.audio_queue = audio_queue
        self.message_callback = message_callback
        self.model = model
        self.language = language
        self.sample_rate = sample_rate
        self.diarization = diarization

        self.is_running = False
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._last_audio_sent = 0.0
        self._word_buffer: List[dict] = []

    def _build_ws_url(self) -> str:
        params = {
            "model": self.model,
            "language": self.language,
            "encoding": "linear16",
            "sample_rate": self.sample_rate,
            "channels": 1,
            "interim_results": "true",
            "diarize": "true" if self.diarization else "false",
            "punctuate": "true",
            "smart_format": "true",
            "endpointing": 800,
            "utterance_end_ms": 1500,
            "vad_events": "true",
        }
        base_params = urllib.parse.urlencode(params)
        url = f"wss://api.deepgram.com/v1/listen?{base_params}"

        for term in IMPORTANT_KEYTERMS[:30]:
            url += f"&keyterm={urllib.parse.quote(term)}"
        return url

    async def connect(self) -> bool:
        url = self._build_ws_url()
        try:
            headers = [("Authorization", f"Token {self.api_key}")]
            self.ws = await websockets.connect(url, additional_headers=headers)
            print("[Deepgram] Connected")
            return True
        except Exception as e:
            print(f"[Deepgram] Connection error: {e}")
            # Fallback: minimal params
            if "400" in str(e):
                try:
                    minimal_url = (
                        f"wss://api.deepgram.com/v1/listen?"
                        f"model={self.model}&language={self.language}&"
                        f"encoding=linear16&sample_rate={self.sample_rate}&channels=1"
                    )
                    self.ws = await websockets.connect(
                        minimal_url, additional_headers=headers
                    )
                    print("[Deepgram] Connected (minimal params)")
                    return True
                except Exception as e2:
                    print(f"[Deepgram] Minimal also failed: {e2}")
            return False

    async def disconnect(self):
        if self.ws:
            try:
                await self.ws.send(json.dumps({"type": "CloseStream"}))
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
                    self._keepalive_loop(),
                )
            except websockets.exceptions.ConnectionClosed:
                if self.is_running:
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)
            except Exception as e:
                print(f"[Deepgram] Run error: {e}")
                if self.is_running:
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)

    async def _send_audio_loop(self):
        while self.is_running and self.ws:
            try:
                chunk = await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
                if chunk:
                    timestamp, audio_data = chunk
                    await self.ws.send(audio_data)
                    self._last_audio_sent = time.monotonic()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[Deepgram] Send error: {e}")
                break

    async def _receive_loop(self):
        async for message in self.ws:
            if not self.is_running:
                break
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")
                if msg_type == "Results":
                    self._handle_results(data)
                elif msg_type == "UtteranceEnd":
                    self._handle_utterance_end()
            except Exception as e:
                print(f"[Deepgram] Receive error: {e}")

    async def _keepalive_loop(self):
        while self.is_running and self.ws:
            await asyncio.sleep(5)
            elapsed = time.monotonic() - self._last_audio_sent
            if elapsed > 4:
                try:
                    await self.ws.send(json.dumps({"type": "KeepAlive"}))
                except Exception:
                    break

    def _handle_results(self, data: dict):
        try:
            channel = data.get("channel", {})
            alternatives = channel.get("alternatives", [])
            if not alternatives:
                return
            alt = alternatives[0]
            transcript = alt.get("transcript", "").strip()
            words = alt.get("words", [])
            if not transcript:
                return

            is_final = data.get("is_final", False)
            speech_final = data.get("speech_final", False)

            if not is_final:
                return

            if words:
                self._word_buffer.extend(words)

            if speech_final:
                self._emit_buffered_segments()
        except Exception as e:
            print(f"[Deepgram] Handle results error: {e}")

    def _handle_utterance_end(self):
        if self._word_buffer:
            self._emit_buffered_segments()

    def _emit_buffered_segments(self):
        if not self._word_buffer:
            return
        segments = self._group_words_by_speaker(self._word_buffer)
        for segment in segments:
            self.message_callback(segment, is_partial=False)
        self._word_buffer = []

    def _group_words_by_speaker(self, words: List[dict]) -> List[TranscriptSegment]:
        if not words:
            return []
        segments = []
        current_speaker = None
        current_words = []

        for word in words:
            speaker = word.get("speaker", None)
            speaker_label = f"DG_S{speaker}" if speaker is not None else "Unknown"
            if current_speaker is None:
                current_speaker = speaker_label
                current_words = [word]
            elif speaker_label == current_speaker:
                current_words.append(word)
            else:
                seg = self._words_to_segment(current_words, current_speaker)
                if seg:
                    segments.append(seg)
                current_speaker = speaker_label
                current_words = [word]

        if current_words:
            seg = self._words_to_segment(current_words, current_speaker)
            if seg:
                segments.append(seg)
        return segments

    def _words_to_segment(self, words: List[dict], speaker: str) -> Optional[TranscriptSegment]:
        if not words:
            return None
        text_parts = [w.get("punctuated_word") or w.get("word", "") for w in words]
        text = " ".join(text_parts).strip()
        if not text:
            return None
        start_time = words[0].get("start", 0.0)
        end_time = words[-1].get("end", 0.0)
        confidences = [w.get("confidence", 0) for w in words if "confidence" in w]
        avg_confidence = sum(confidences) / len(confidences) if confidences else None
        return TranscriptSegment(
            speaker=speaker, text=text,
            start_time=start_time, end_time=end_time,
            timestamp=datetime.now(), confidence=avg_confidence,
        )

    def stop(self):
        self.is_running = False
