"""Офлайн-распознавание идёт через STT-провайдера из настроек пользователя."""

from app.core.batch.processor import pick_batch_stt
from app.core.batch.deepgram_transcription_service import DeepgramBatchTranscriptionService
from app.core.batch.utils import group_words_by_speaker

KEYS = {"deepgram": "dg", "elevenlabs": "el"}


def test_pick_follows_user_choice():
    assert pick_batch_stt("deepgram", KEYS) == ("deepgram", "dg")
    assert pick_batch_stt("elevenlabs", KEYS) == ("elevenlabs", "el")


def test_pick_falls_back_when_no_key_or_unsupported():
    assert pick_batch_stt("deepgram", {"elevenlabs": "el"}) == ("elevenlabs", "el")
    assert pick_batch_stt("speechmatics", KEYS) == ("deepgram", "dg")
    assert pick_batch_stt(None, {}) is None


def test_deepgram_response_parsed_into_batch_format():
    data = {"results": {"channels": [{"alternatives": [{
        "transcript": "привет мир. да",
        "words": [
            {"word": "привет", "punctuated_word": "Привет", "start": 0.1, "end": 0.5, "speaker": 0},
            {"word": "мир", "punctuated_word": "мир.", "start": 0.6, "end": 0.9, "speaker": 0},
            {"word": "да", "punctuated_word": "Да.", "start": 1.2, "end": 1.4, "speaker": 1},
        ],
    }]}]}}
    t = DeepgramBatchTranscriptionService("k")._parse_response(data)
    assert t["text"] == "привет мир. да"
    segs = group_words_by_speaker(t["words"])
    assert [(s.speaker, s.text) for s in segs] == [
        ("Speaker_speaker_0", "Привет мир."), ("Speaker_speaker_1", "Да."),
    ]


def test_deepgram_empty_response():
    assert DeepgramBatchTranscriptionService("k")._parse_response({}) == {"text": "", "words": []}
