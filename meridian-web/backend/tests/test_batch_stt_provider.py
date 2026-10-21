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


# ---------- GigaAM ----------

import pytest
import requests
from pydantic import ValidationError

from app.core.batch import gigaam_transcription_service as giga
from app.core.batch.gigaam_transcription_service import GigaAMBatchTranscriptionService
from app.core.batch.processor import ordered_batch_stt
from app.schemas.settings import UserSettingsUpdate

GIGA_URL = "http://asr-tunnel:18763"
KEYS_GIGA = {**KEYS, "gigaam": GIGA_URL}


def test_ordered_chosen_gigaam_first():
    assert ordered_batch_stt("gigaam", KEYS_GIGA) == [
        ("gigaam", GIGA_URL), ("deepgram", "dg"), ("elevenlabs", "el"),
    ]


def test_ordered_gigaam_without_url_falls_back_to_keys():
    assert ordered_batch_stt("gigaam", KEYS) == [("deepgram", "dg"), ("elevenlabs", "el")]
    assert pick_batch_stt("gigaam", KEYS) == ("deepgram", "dg")


def test_ordered_gigaam_last_in_automatic_order():
    assert ordered_batch_stt(None, KEYS_GIGA)[-1] == ("gigaam", GIGA_URL)
    assert pick_batch_stt(None, KEYS_GIGA) == ("deepgram", "dg")
    assert pick_batch_stt(None, {"gigaam": GIGA_URL}) == ("gigaam", GIGA_URL)


def test_gigaam_result_normalized():
    result = {
        "text": "Привет. Да.",
        "words": [
            {"text": "Привет.", "start": 0.1, "end": 0.5, "speaker_id": "Speaker_SPEAKER_00"},
            {"text": "Да.", "start": 1.2, "end": 1.4, "speaker_id": "Speaker_SPEAKER_03"},
            {"text": "Угу", "start": 2.0, "end": 2.2},
        ],
    }
    t = GigaAMBatchTranscriptionService(GIGA_URL)._parse_result(result)
    assert t["text"] == "Привет. Да."
    assert [w["speaker_id"] for w in t["words"]] == [
        "Speaker_speaker_0", "Speaker_speaker_3", "Speaker_1",
    ]


def test_gigaam_empty_words_keeps_text():
    t = GigaAMBatchTranscriptionService(GIGA_URL)._parse_result({"text": "просто текст", "words": []})
    assert t == {"text": "просто текст", "words": []}


class _Resp:
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self._data = data or {}
        self.text = ""

    def json(self):
        return self._data


def _patch_http(monkeypatch, post_codes, polls):
    calls = {"post": 0, "get": []}
    poll_iter = iter(polls)

    def fake_get(url, **kwargs):
        calls["get"].append(url)
        if url.endswith("/api/session"):
            return _Resp(200, {"token": "tok"})
        return _Resp(200, next(poll_iter))

    def fake_post(url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
        assert kwargs["data"] == {"model": "gigaam-v3", "diarize": "true"}
        code = post_codes[calls["post"]]
        calls["post"] += 1
        return _Resp(code, {"id": "job1"} if code == 200 else {})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(giga.time, "sleep", lambda s: None)
    return calls


@pytest.mark.asyncio
async def test_gigaam_flow_retry_then_done(monkeypatch, tmp_path):
    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"x")
    calls = _patch_http(monkeypatch, [503, 200], [
        {"status": "processing"},
        {"status": "done", "result": {
            "text": "да", "words": [
                {"text": "да", "start": 0, "end": 1, "speaker_id": "Speaker_SPEAKER_01"}],
        }},
    ])
    t = await GigaAMBatchTranscriptionService(GIGA_URL + "/").transcribe(str(audio), timeout=60)
    assert t == {"text": "да", "words": [
        {"text": "да", "start": 0, "end": 1, "speaker_id": "Speaker_speaker_1"}]}
    assert calls["post"] == 2
    assert calls["get"][0] == f"{GIGA_URL}/api/session"


@pytest.mark.asyncio
async def test_gigaam_flow_failed_returns_none(monkeypatch, tmp_path):
    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"x")
    _patch_http(monkeypatch, [200], [{"status": "failed", "error": "boom"}])
    assert await GigaAMBatchTranscriptionService(GIGA_URL).transcribe(str(audio), timeout=60) is None


def test_batch_stt_provider_validator():
    assert UserSettingsUpdate(batch_stt_provider="").batch_stt_provider == ""
    assert UserSettingsUpdate(batch_stt_provider="gigaam").batch_stt_provider == "gigaam"
    assert UserSettingsUpdate().batch_stt_provider is None
    with pytest.raises(ValidationError):
        UserSettingsUpdate(batch_stt_provider="speechmatics")
