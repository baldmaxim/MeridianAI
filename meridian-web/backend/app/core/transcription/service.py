"""ElevenLabs batch transcription service."""

import io
import wave
import requests
from typing import List
from datetime import datetime
from .models import TranscriptSegment


# Boosted keywords for construction domain
BOOSTED_KEYWORDS = [
    "комплект", "смета", "договор", "КС-2", "КС-3", "КС-6", "КС-11",
    "СУ-10", "акт", "протокол", "спецификация", "ведомость",
    "бюджет", "стоимость", "цена", "оплата", "аванс", "предоплата",
    "генподряд", "генподрядчик", "субподряд", "субподрядчик",
    "заказчик", "застройщик", "инвестор", "проектировщик",
    "работы", "объем", "монтаж", "демонтаж", "строительство",
    "материалы", "оборудование", "техника", "бетон", "арматура",
    "срок", "график", "дедлайн", "этап", "задержка",
    "качество", "брак", "дефект", "гарантия", "сертификат",
    "штраф", "пеня", "неустойка", "компенсация",
]


class TranscriptionService:
    """ElevenLabs API transcription client (batch mode)."""

    def __init__(self, api_key: str, model_id: str = "scribe_v1",
                 language_code: str = "ru"):
        self.api_key = api_key
        self.model_id = model_id
        self.language_code = language_code
        self.base_url = "https://api.elevenlabs.io/v1/speech-to-text"
        self.session = requests.Session()
        self.session.headers.update({"xi-api-key": api_key})

    def _create_wav_file(self, audio_data: bytes) -> bytes:
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(audio_data)
        wav_buffer.seek(0)
        return wav_buffer.read()

    def transcribe_audio(self, audio_data: bytes) -> List[TranscriptSegment]:
        try:
            wav_data = self._create_wav_file(audio_data)
            files = [
                ('audio', ('audio.wav', wav_data, 'audio/wav')),
                ('model_id', (None, self.model_id)),
                ('language_code', (None, self.language_code)),
                ('diarize', (None, 'true')),
                ('word_timestamps', (None, 'true'))
            ]
            for keyword in BOOSTED_KEYWORDS:
                files.append(('boosted_keywords', (None, keyword)))

            response = self.session.post(self.base_url, files=files, timeout=30)
            if response.status_code == 200:
                return self._parse_response(response.json())
            else:
                print(f"Transcription error: {response.status_code}")
                return []
        except Exception as e:
            print(f"Transcription failed: {e}")
            return []

    def _parse_response(self, data: dict) -> List[TranscriptSegment]:
        segments = []
        text = data.get("text", "")
        if not text:
            return segments

        words = data.get("words", [])
        if words:
            current_speaker = None
            current_text = []
            start_time = 0.0
            for word_data in words:
                speaker = word_data.get("speaker_id", "Unknown")
                word_text = word_data.get("text", "")
                if speaker != current_speaker:
                    if current_text:
                        segments.append(TranscriptSegment(
                            speaker=current_speaker or "Unknown",
                            text=" ".join(current_text),
                            start_time=start_time,
                            end_time=word_data.get("start", 0.0),
                            timestamp=datetime.now(),
                        ))
                    current_speaker = speaker
                    current_text = [word_text]
                    start_time = word_data.get("start", 0.0)
                else:
                    current_text.append(word_text)
            if current_text:
                segments.append(TranscriptSegment(
                    speaker=current_speaker or "Unknown",
                    text=" ".join(current_text),
                    start_time=start_time,
                    end_time=words[-1].get("end", 0.0) if words else 0.0,
                    timestamp=datetime.now(),
                ))
        else:
            segments.append(TranscriptSegment(
                speaker="Unknown", text=text,
                start_time=0.0, end_time=0.0, timestamp=datetime.now(),
            ))
        return segments
