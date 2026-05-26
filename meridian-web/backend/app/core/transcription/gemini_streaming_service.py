"""Gemini Flash batch-based transcription service.

Adapted for web: uses asyncio.Queue instead of threading queue.
"""

import asyncio
import json
from datetime import datetime
from typing import Callable, Optional

from google import genai
from google.genai import types

from .models import TranscriptSegment


class GeminiStreamingTranscriptionService:
    """Transcription using Gemini Flash API (batch-based, not true streaming)."""

    def __init__(self, api_key: str, audio_queue: asyncio.Queue,
                 message_callback: Callable,
                 model: str = "gemini-2.5-flash",
                 language: str = "ru",
                 chunk_duration_seconds: int = 5,
                 sample_rate: int = 16000):
        self.api_key = api_key
        self.audio_queue = audio_queue
        self.message_callback = message_callback
        self.model = model
        self.language = language
        self.chunk_duration_seconds = chunk_duration_seconds
        self.sample_rate = sample_rate

        self.is_running = False
        self._audio_buffer: bytes = b""
        self._buffer_start_time: Optional[datetime] = None

        self.client = genai.Client(api_key=api_key)

    async def run(self):
        self.is_running = True
        while self.is_running:
            try:
                await self._accumulate_audio()
                if len(self._audio_buffer) > 0:
                    buffer_duration = len(self._audio_buffer) / (self.sample_rate * 2)
                    if buffer_duration >= self.chunk_duration_seconds:
                        await self._transcribe_buffer()
            except Exception as e:
                print(f"[Gemini] Error: {e}")
                await asyncio.sleep(1)

    async def _accumulate_audio(self):
        try:
            chunk = await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
            if chunk:
                timestamp, audio_data = chunk
                if self._buffer_start_time is None:
                    self._buffer_start_time = timestamp
                self._audio_buffer += audio_data
        except asyncio.TimeoutError:
            pass

    async def _transcribe_buffer(self):
        if not self._audio_buffer:
            return
        try:
            audio_part = types.Part(
                inline_data=types.Blob(mime_type="audio/pcm", data=self._audio_buffer)
            )
            prompt = self._build_prompt()
            response = await asyncio.to_thread(self._call_gemini, audio_part, prompt)
            if response:
                self._parse_and_emit(response)
        except Exception as e:
            print(f"[Gemini] Transcription error: {e}")
        finally:
            self._audio_buffer = b""
            self._buffer_start_time = None

    def _build_prompt(self) -> str:
        lang_name = "Russian" if self.language == "ru" else self.language
        return f"""Transcribe this audio accurately in {lang_name}.

Requirements:
1. Identify distinct speakers (Speaker 1, Speaker 2, etc.)
2. Provide the exact spoken text
3. The audio is from a business negotiation in construction industry

Output format: JSON with segments array, each segment has:
- speaker: string (e.g., "Speaker 1")
- content: string (the transcribed text)
"""

    def _call_gemini(self, audio_part: types.Part, prompt: str) -> Optional[str]:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[types.Content(parts=[audio_part, types.Part(text=prompt)])],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "segments": types.Schema(
                                type=types.Type.ARRAY,
                                items=types.Schema(
                                    type=types.Type.OBJECT,
                                    properties={
                                        "speaker": types.Schema(type=types.Type.STRING),
                                        "content": types.Schema(type=types.Type.STRING),
                                    },
                                    required=["speaker", "content"],
                                ),
                            ),
                        },
                        required=["segments"],
                    ),
                ),
            )
            return response.text
        except Exception as e:
            print(f"[Gemini] API error: {e}")
            return None

    def _parse_and_emit(self, response_text: str):
        try:
            data = json.loads(response_text)
            for seg in data.get("segments", []):
                speaker = seg.get("speaker", "Unknown")
                content = seg.get("content", "").strip()
                if not content:
                    continue
                if "1" in speaker:
                    speaker = "GM_S0"
                elif "2" in speaker:
                    speaker = "GM_S1"
                else:
                    speaker = "GM_S0"
                segment = TranscriptSegment(
                    speaker=speaker, text=content,
                    start_time=0.0, end_time=0.0, timestamp=datetime.now(),
                )
                self.message_callback(segment, is_partial=False)
        except json.JSONDecodeError as e:
            print(f"[Gemini] JSON parse error: {e}")

    def stop(self):
        self.is_running = False
