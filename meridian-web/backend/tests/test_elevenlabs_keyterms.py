# -*- coding: utf-8 -*-
"""Словарь терминов как keyterms ElevenLabs (batch scribe_v3 и live scribe_v3_live)."""

import asyncio
from types import SimpleNamespace

import pytest
import requests

from app.core.batch import processor as proc
from app.core.batch.deepgram_transcription_service import DeepgramBatchTranscriptionService
from app.core.batch.transcription_service import BatchTranscriptionService
from app.core.transcription.streaming_service import StreamingTranscriptionService
from app.services.asr_lexicon import build_keyterms


def _build(entries, **kw):
    kw.setdefault("limit", 100)
    kw.setdefault("max_chars", 50)
    return build_keyterms(entries, **kw)


# ---------- build_keyterms ----------

def test_keyterms_source_order_and_priority():
    entries = [
        ("бетон", [], "base"),
        ("Глоссарий", [], "glossary"),
        ("Термин", [], "asr_terms"),
        ("ООО Заказчик", [], "directory"),
    ]
    assert _build(entries) == ["ООО Заказчик", "Термин", "Глоссарий", "бетон"]
    assert _build(entries, priority_terms=["Иван Петров"])[0] == "Иван Петров"


def test_keyterms_only_canonical_terms_not_aliases():
    assert _build([("машино-место", ["машины места"], "base")]) == ["машино-место"]


def test_keyterms_filters():
    entries = [
        ("ab", [], "base"),                      # короче 3
        ("  бетон  ", [], "base"),               # пробелы по краям срезаются
        ("Бетон", [], "directory"),              # дубль без учёта регистра
        ("x" * 51, [], "base"),                  # длиннее max_chars
        ("один два три четыре пять шесть", [], "base"),  # > 5 слов
        ("a<b", [], "base"), ("a>b", [], "base"), ("a{b}", [], "base"),
        ("a[b]", [], "base"), ("a\\b", [], "base"),
        ("", [], "base"),
        ("КС-2", [], "base"),
    ]
    assert _build(entries) == ["Бетон", "КС-2"]


def test_keyterms_max_chars_and_words_params():
    entries = [("двадцать один символ__", [], "base"), ("раз два три", [], "base")]
    assert _build(entries, max_chars=20) == ["раз два три"]
    assert _build(entries, max_words=2) == []


def test_keyterms_limit_cuts_in_priority_order():
    entries = [(f"база{i}", [], "base") for i in range(10)] + [("Заказчик", [], "directory")]
    assert _build(entries, limit=3, priority_terms=["Приоритет"]) == ["Приоритет", "Заказчик", "база0"]
    assert _build(entries, limit=0) == []


# ---------- batch: тело запроса ----------

class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text

    def json(self):
        return {"text": "", "words": []}


def _patch_post(monkeypatch, responses):
    calls: list[dict] = []

    def fake_post(url, **kwargs):
        calls.append({**kwargs, "data": dict(kwargs["data"])})
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(requests, "post", fake_post)
    return calls


@pytest.fixture
def audio(tmp_path):
    f = tmp_path / "a.ogg"
    f.write_bytes(b"x")
    return str(f)


@pytest.mark.asyncio
async def test_batch_sends_keyterms_and_digits(monkeypatch, audio):
    calls = _patch_post(monkeypatch, [_Resp()])
    await BatchTranscriptionService("k", max_speakers=2, keyterms=["бетон", "КС-2"]).transcribe(audio)
    data = calls[0]["data"]
    assert data["keyterms"] == ["бетон", "КС-2"]
    assert "numbers_format" not in data
    assert data["diarize"] == "true" and data["timestamps_granularity"] == "word"
    assert data["num_speakers"] == "2" and data["model_id"] == "scribe_v3"


def test_batch_multipart_body_has_repeated_keyterms_fields():
    req = requests.Request(
        "POST", "http://x", data={"model_id": "scribe_v3", "keyterms": ["бетон", "КС-2"]},
        files={"file": ("a.ogg", b"x")},
    ).prepare()
    body = req.body.decode("utf-8", "ignore")
    assert body.count('name="keyterms"') == 2
    assert "бетон" in body and "КС-2" in body


@pytest.mark.asyncio
async def test_batch_without_keyterms_omits_field_but_keeps_digits(monkeypatch, audio):
    calls = _patch_post(monkeypatch, [_Resp()])
    await BatchTranscriptionService("k").transcribe(audio)
    assert "keyterms" not in calls[0]["data"]
    assert "numbers_format" not in calls[0]["data"]


@pytest.mark.asyncio
async def test_batch_retries_once_without_keyterms_on_400(monkeypatch, audio):
    calls = _patch_post(monkeypatch, [_Resp(400, '{"detail": "invalid keyterms"}'), _Resp()])
    result = await BatchTranscriptionService("k", keyterms=["бетон"]).transcribe(audio)
    assert result is not None
    assert len(calls) == 2
    assert "keyterms" in calls[0]["data"] and "keyterms" not in calls[1]["data"]


@pytest.mark.asyncio
async def test_batch_400_without_keyterms_mention_is_not_retried(monkeypatch, audio):
    calls = _patch_post(monkeypatch, [_Resp(400, "bad audio")])
    assert await BatchTranscriptionService("k", keyterms=["бетон"]).transcribe(audio) is None
    assert len(calls) == 1


def test_deepgram_service_unchanged_and_keyterms_only_for_elevenlabs():
    assert DeepgramBatchTranscriptionService("k", max_speakers=2).max_speakers == 2
    assert BatchTranscriptionService("k").keyterms == []
    assert proc.BATCH_STT["elevenlabs"][1] is BatchTranscriptionService


# ---------- live: SDK-опции ----------

def _live_service(keyterms, connect):
    svc = StreamingTranscriptionService(
        api_key="k", audio_queue=asyncio.Queue(),
        on_partial=lambda p: None, on_committed=lambda c: None, keyterms=keyterms,
    )
    svc.client = SimpleNamespace(speech_to_text=SimpleNamespace(realtime=SimpleNamespace(connect=connect)))
    return svc


@pytest.mark.asyncio
async def test_live_passes_keyterms_to_sdk_options():
    seen = []

    async def connect(options):
        seen.append(options)
        return object()

    assert await _live_service(["бетон", "КС-2"], connect).connect() is True
    assert seen[0]["keyterms"] == ["бетон", "КС-2"]
    assert seen[0]["model_id"] == "scribe_v3_live"


@pytest.mark.asyncio
async def test_live_no_keyterms_key_when_empty():
    seen = []

    async def connect(options):
        seen.append(options)
        return object()

    assert await _live_service(None, connect).connect() is True
    assert "keyterms" not in seen[0]


@pytest.mark.asyncio
async def test_live_falls_back_without_keyterms_on_connect_error():
    seen = []

    async def connect(options):
        seen.append(options)
        if "keyterms" in options:
            raise RuntimeError("bad keyterms")
        return object()

    svc = _live_service(["бетон"], connect)
    assert await svc.connect() is True
    assert len(seen) == 2 and "keyterms" not in seen[1]
    assert svc.keyterms == []
