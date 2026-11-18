# -*- coding: utf-8 -*-
"""ElevenLabs Scribe v3 Live: прямой WebSocket (реконнект, keepalive, previous_text, деградация,
диаризация, язык, устаревшие чанки). Сервер — настоящий websockets.serve на localhost."""

import asyncio
import base64
import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.asyncio.server import serve

from app.core.transcription.elevenlabs_live_protocol import (
    DiarizationTracker, LiveOptions, SessionTimeline, build_ws_url, clip_keyterm_library,
    trim_previous_text,
)
from app.core.transcription.streaming_service import StreamingTranscriptionService

PCM_100MS = bytes(3200)


def _opts(**kw) -> LiveOptions:
    kw.setdefault("keepalive_secs", 60)
    return LiveOptions(secondary_languages=("tr",), **kw)


class FakeServer:
    """script(ws, conn, idx) — поведение сервера на соединение; по умолчанию — читать всё."""

    def __init__(self, script=None):
        self.script = script or self.read_all
        self.conns: list[dict] = []
        self._server = None
        self.url = ""

    @staticmethod
    async def read_all(ws, conn, idx):
        async for raw in ws:
            conn["msgs"].append(json.loads(raw))

    async def _handler(self, ws):
        conn = {"path": ws.request.path, "key": ws.request.headers.get("xi-api-key"), "msgs": []}
        self.conns.append(conn)
        await self.script(ws, conn, len(self.conns) - 1)

    async def __aenter__(self):
        self._server = await serve(self._handler, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/v1/speech-to-text/realtime"
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()


def _query(conn) -> dict:
    return parse_qs(urlsplit(conn["path"]).query)


async def _until(cond, timeout=5.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("условие не выполнилось за таймаут")
        await asyncio.sleep(0.02)


class _Recorder:
    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, data):
        self.chunks.append(data)


def _service(server, queue=None, **kw):
    committed, partials, errors, speakers = [], [], [], []
    svc = StreamingTranscriptionService(
        api_key="test-key", audio_queue=queue or asyncio.Queue(),
        on_partial=partials.append, on_committed=committed.append,
        on_error=lambda t, m: errors.append((t, m)),
        on_speaker=lambda seg, label: speakers.append((seg, label)),
        options=kw.pop("options", _opts()), **kw,
    )
    svc.ws_url = server.url
    svc.backoff_start = 0.05
    svc.backoff_max = 0.2
    svc.poll_secs = 0.02
    svc.committed, svc.partials, svc.errors, svc.speakers = committed, partials, errors, speakers
    return svc


async def _run(svc, body):
    task = asyncio.create_task(svc.run())
    try:
        await body()
    finally:
        svc.stop()
        try:
            await asyncio.wait_for(task, 5)
        except asyncio.TimeoutError:
            task.cancel()


def _committed_msg(text, language="ru", words=None, index=None):
    msg = {"message_type": "committed_transcript_with_timestamps", "text": text,
           "language_code": language,
           "words": words or [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4, "type": "word", "logprob": -0.1}
                              for i, w in enumerate(text.split())]}
    if index is not None:
        msg["segment_index"] = index
    return msg


# ---------- (1) закрытие сокета сервером → реконнект ----------

async def test_reconnects_after_server_closes_socket():
    async def script(ws, conn, idx):
        if idx == 0:
            await ws.recv()
            await ws.close()
        else:
            await FakeServer.read_all(ws, conn, idx)

    async with FakeServer(script) as server:
        queue = asyncio.Queue()
        await queue.put((datetime.now(), PCM_100MS))
        svc = _service(server, queue)

        async def body():
            await _until(lambda: len(server.conns) >= 2)
            assert server.conns[0]["key"] == "test-key"

        await _run(svc, body)


async def test_reconnects_when_server_closes_idle_socket():
    """Главный баг SDK-версии: очередь пуста, сервер закрыл сокет — сервис не должен зависнуть."""
    async def script(ws, conn, idx):
        if idx == 0:
            await ws.close()
        else:
            await FakeServer.read_all(ws, conn, idx)

    async with FakeServer(script) as server:
        svc = _service(server)

        async def body():
            await _until(lambda: len(server.conns) >= 2)

        await _run(svc, body)


# ---------- (2) keepalive-тишина ----------

async def test_keepalive_silence_when_queue_empty_with_first_chunk_extras():
    async with FakeServer() as server:
        svc = _service(server, options=_opts(keepalive_secs=0.2), keyterm_library=["бетон", "КС-2"])

        async def body():
            await _until(lambda: len(server.conns) and len(server.conns[0]["msgs"]) >= 2)

        await _run(svc, body)
        first, second = server.conns[0]["msgs"][:2]
        assert first["message_type"] == "input_audio_chunk" and first["commit"] is False
        assert first["sample_rate"] == 16000
        assert base64.b64decode(first["audio_base_64"]) == bytes(3200)  # 100 мс нулей PCM16
        assert first["previous_text"] == svc.PREVIOUS_TEXT
        assert first["keyterm_library"] == ["бетон", "КС-2"]
        assert "previous_text" not in second and "keyterm_library" not in second


# ---------- (3) previous_text из последнего committed ----------

async def test_previous_text_from_last_committed_on_reconnect():
    text = "Мы согласны на аванс при условии подписания дополнительного соглашения до пятницы"

    async def script(ws, conn, idx):
        if idx == 0:
            await ws.recv()
            await ws.send(json.dumps(_committed_msg(text)))
            await asyncio.sleep(0.2)
            await ws.close()
        else:
            await FakeServer.read_all(ws, conn, idx)

    async with FakeServer(script) as server:
        queue = asyncio.Queue()
        svc = _service(server, queue, options=_opts(keepalive_secs=0.3))
        await queue.put((datetime.now(), PCM_100MS))

        async def body():
            await _until(lambda: len(server.conns) >= 2 and server.conns[1]["msgs"])

        await _run(svc, body)
        previous = server.conns[1]["msgs"][0]["previous_text"]
        assert 0 < len(previous) <= 50
        assert text.endswith(previous)
        assert previous != svc.PREVIOUS_TEXT
        assert previous[0] != " " and text[text.index(previous) - 1] == " "  # начало — граница слова


# ---------- (4) деградация опций ----------

async def test_degrades_options_on_invalid_request_then_keeps_level():
    async def script(ws, conn, idx):
        if idx == 0:
            await ws.send(json.dumps({"message_type": "invalid_request", "error": "multilang_mode"}))
        elif idx == 1:
            await ws.send(json.dumps({"message_type": "input_error", "error": "keyterms"}))
        elif idx == 2:
            await ws.close()  # принятый уровень держится и при обычном реконнекте
            return
        await FakeServer.read_all(ws, conn, idx)

    async with FakeServer(script) as server:
        svc = _service(server, options=_opts(keepalive_secs=0.2),
                       keyterms=["бетон"], keyterm_library=["бетон"])

        async def body():
            await _until(lambda: len(server.conns) >= 4)

        await _run(svc, body)
        q0, q1, q2, q3 = (_query(c) for c in server.conns[:4])
        assert q0["multilang_mode"] == ["true"] and q0["diarize"] == ["true"]
        assert q0["commit_strategy"] == ["turn_prediction"] and q0["secondary_languages"] == ["tr"]
        assert q0["keyterms"] == ["бетон"] and "keepalive_interval_ms" in q0
        for q in (q1, q2, q3):  # «новые» опции сняты
            assert "multilang_mode" not in q and "diarize" not in q and "secondary_languages" not in q
            assert "keepalive_interval_ms" not in q and q["commit_strategy"] == ["vad"]
        assert q1["keyterms"] == ["бетон"]
        assert "keyterms" not in q2 and "keyterms" not in q3
        assert svc._degrade_level == 2
        assert svc.errors == []  # шаги деградации в UI не показываем
        # keyterm_library на полном уровне — в тесте keepalive; после деградации не уходит
        assert not any("keyterm_library" in m for c in server.conns[1:4] for m in c["msgs"])


async def test_accepted_level_is_kept_after_late_invalid_request():
    """Уровень, на котором уже был committed, не снижается из-за случайной ошибки на реконнекте."""
    async def script(ws, conn, idx):
        if idx == 0:
            await ws.recv()
            await ws.send(json.dumps(_committed_msg("добрый день")))
            await asyncio.sleep(0.1)
            await ws.close()
        elif idx == 1:
            await ws.send(json.dumps({"message_type": "invalid_request", "error": "случайность"}))
            await asyncio.sleep(0.3)
        else:
            await FakeServer.read_all(ws, conn, idx)

    async with FakeServer(script) as server:
        queue = asyncio.Queue()
        await queue.put((datetime.now(), PCM_100MS))
        svc = _service(server, queue)

        async def body():
            await _until(lambda: len(server.conns) >= 3)

        await _run(svc, body)
        assert svc._degrade_level == 0
        for conn in server.conns[:3]:
            assert _query(conn)["multilang_mode"] == ["true"]
        assert svc.errors and svc.errors[0][0] == "invalid_request"  # обычный путь: в UI + backoff


async def test_fatal_error_stops_service():
    async def script(ws, conn, idx):
        await ws.send(json.dumps({"message_type": "auth_error", "error": "bad key"}))
        await asyncio.sleep(0.5)

    async with FakeServer(script) as server:
        svc = _service(server)
        task = asyncio.create_task(svc.run())
        await asyncio.wait_for(task, 5)
        assert svc.errors == [("auth_error", "bad key")]
        assert len(server.conns) == 1


async def test_throttle_error_reconnects_and_reports():
    async def script(ws, conn, idx):
        if idx == 0:
            await ws.send(json.dumps({"message_type": "commit_throttled", "error": "slow down"}))
            await asyncio.sleep(0.5)
        else:
            await FakeServer.read_all(ws, conn, idx)

    async with FakeServer(script) as server:
        svc = _service(server)

        async def body():
            await _until(lambda: len(server.conns) >= 2)

        await _run(svc, body)
        assert svc.errors[0][0] == "commit_throttled"


# ---------- (5) диаризация ----------

def _diarized(index, text, speakers):
    return {"message_type": "diarized_transcript", "segment_index": index, "text": text,
            "words": [{"text": f"w{i}", "type": "word", "speaker_id": s} for i, s in enumerate(speakers)]}


async def test_diarized_transcript_calls_on_speaker_with_merges():
    async def script(ws, conn, idx):
        await ws.recv()
        await ws.send(json.dumps({"message_type": "committed_transcript", "segment_index": 0, "text": "один два три"}))
        await ws.send(json.dumps(_committed_msg("один два три")))
        await ws.send(json.dumps(_diarized(0, "один два три", ["speaker_0", "speaker_1", "speaker_1", None])))
        await ws.send(json.dumps({"message_type": "committed_transcript", "segment_index": 1, "text": "четыре пять"}))
        await ws.send(json.dumps(_committed_msg("четыре пять")))
        await ws.send(json.dumps(_diarized(1, "четыре пять", ["speaker_0", "speaker_0"])))
        await ws.send(json.dumps({"message_type": "speakers_merged",
                                  "from_speaker_id": "speaker_1", "to_speaker_id": "speaker_0"}))
        await FakeServer.read_all(ws, conn, idx)

    async with FakeServer(script) as server:
        queue = asyncio.Queue()
        await queue.put((datetime.now(), PCM_100MS))
        svc = _service(server, queue)

        async def body():
            await _until(lambda: len(svc.speakers) >= 3)

        await _run(svc, body)
        first, second = svc.committed
        labels = [(seg.text, label) for seg, label in svc.speakers]
        # самый частый не-null speaker_id; метка с номером сессии
        assert labels[0] == ("один два три", "s1_speaker_1")
        assert labels[1] == ("четыре пять", "s1_speaker_0")
        # слияние speaker_1 → speaker_0 меняет метку первой реплики
        assert labels[2] == ("один два три", "s1_speaker_0")
        assert first.speaker_id == "unknown_speaker"  # speaker_id не трогаем


def test_tracker_matches_by_text_when_index_drifts_and_handles_early_diarized():
    tracker = DiarizationTracker(2)
    seg_a, seg_b = object(), object()
    # diarized пришёл раньше сегмента
    assert tracker.on_diarized(_diarized(5, "привет", ["speaker_3"])) is None
    idx = tracker.next_index(None, "привет")  # свой счётчик = 0, а сервер считает 5 — не совпало
    assert tracker.register(idx, seg_a, "привет") is None
    # индекс не совпал, но текст тот же — находим по тексту
    assert tracker.on_diarized(_diarized(9, "привет", ["speaker_3", "speaker_3"])) == (seg_a, "s2_speaker_3")
    # пустой commit тоже занимает номер в счётчике
    assert tracker.next_index(None, "") == 1
    assert tracker.next_index(None, "дела") == 2
    tracker.register(2, seg_b, "дела")
    # цепочка слияний применяется транзитивно
    tracker.on_diarized(_diarized(2, "дела", ["speaker_1"]))
    assert tracker.on_merged("speaker_1", "speaker_2") == [(seg_b, "s2_speaker_2")]
    assert tracker.on_merged("speaker_2", "speaker_3") == [(seg_b, "s2_speaker_3")]


# ---------- (6) язык ----------

async def test_language_from_committed_goes_to_segment():
    async def script(ws, conn, idx):
        await ws.recv()
        await ws.send(json.dumps(_committed_msg("merhaba nasılsınız", language="tr")))
        await ws.send(json.dumps(_committed_msg("добрый день", language=None)))
        await ws.send(json.dumps({"message_type": "partial_transcript", "text": ""}))
        await ws.send(json.dumps({"message_type": "partial_transcript", "text": "привет"}))
        await FakeServer.read_all(ws, conn, idx)

    async with FakeServer(script) as server:
        queue = asyncio.Queue()
        await queue.put((datetime.now(), PCM_100MS))
        svc = _service(server, queue)

        async def body():
            await _until(lambda: len(svc.committed) >= 2 and svc.partials)

        await _run(svc, body)
        assert [s.language for s in svc.committed] == ["tr", None]
        assert [p.text for p in svc.partials] == ["привет"]  # пустой partial — keepalive сервера


# ---------- (7) устаревшие чанки ----------

async def test_stale_chunks_not_sent_but_recorded():
    async with FakeServer() as server:
        queue = asyncio.Queue()
        old = datetime.now() - timedelta(seconds=40)
        await queue.put((old, b"\x01\x00" * 1600))
        await queue.put((datetime.now(), b"\x02\x00" * 1600))
        recorder = _Recorder()
        svc = _service(server, queue, audio_recorder=recorder)

        async def body():
            await _until(lambda: server.conns and server.conns[0]["msgs"])
            await asyncio.sleep(0.2)

        await _run(svc, body)
        sent = [base64.b64decode(m["audio_base_64"]) for m in server.conns[0]["msgs"]]
        assert sent == [b"\x02\x00" * 1600]
        assert recorder.chunks == [b"\x01\x00" * 1600, b"\x02\x00" * 1600]


# ---------- URL и вспомогательное ----------

def test_build_ws_url_params():
    url = build_ws_url(
        "wss://api.elevenlabs.io/v1/speech-to-text/realtime", model="scribe_v3_live", sample_rate=16000,
        options=LiveOptions(secondary_languages=("tr", "en"), keepalive_secs=5), language_code="ru",
        keyterms=["бетон", "КС-2"], send_keepalive=True,
    )
    q = parse_qs(urlsplit(url).query)
    assert url.startswith("wss://api.elevenlabs.io/v1/speech-to-text/realtime?")
    assert q["model_id"] == ["scribe_v3_live"] and q["audio_format"] == ["pcm_16000"]
    assert q["include_timestamps"] == ["true"] and q["include_language_detection"] == ["true"]
    assert q["language_code"] == ["ru"] and q["secondary_languages"] == ["tr", "en"]
    assert q["commit_strategy"] == ["turn_prediction"] and q["multilang_mode"] == ["true"]
    assert q["vad_silence_threshold_secs"] == ["1.0"] and q["vad_threshold"] == ["0.5"]
    assert q["min_speech_duration_ms"] == ["250"] and q["min_silence_duration_ms"] == ["300"]
    assert q["keyterms"] == ["бетон", "КС-2"] and q["keepalive_interval_ms"] == ["5000"]
    assert "filter_background_audio" not in q


def test_options_from_settings_and_empty_secondary():
    class S:
        elevenlabs_live_language = "ru"
        elevenlabs_live_secondary_languages = " tr , ,en"
        elevenlabs_live_multilang = True
        elevenlabs_live_diarize = False
        elevenlabs_live_commit_strategy = "bogus"
        elevenlabs_live_keyterm_library = True
        elevenlabs_live_keepalive_secs = 5

    o = LiveOptions.from_settings(S())
    assert o.secondary_languages == ("tr", "en") and o.commit_strategy == "vad" and not o.diarize
    S.elevenlabs_live_secondary_languages = ""
    assert LiveOptions.from_settings(S()).secondary_languages == ()


def test_trim_previous_text():
    assert trim_previous_text("короткий текст") == "короткий текст"
    long = "один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать"
    out = trim_previous_text(long)
    assert len(out) <= 50 and long.endswith(out) and out.startswith(("девять", "десять", "восемь", "семь"))
    assert trim_previous_text("") == ""


def test_clip_keyterm_library_limits():
    assert clip_keyterm_library(["a", "", "  ", "x" * 51, "ok"]) == ["a", "ok"]
    assert len(clip_keyterm_library([f"т{i}" for i in range(20000)])) == 10000
    big = ["я" * 50] * 30000  # 100 байт UTF-8 на термин → потолок 2 МБ
    assert sum(len(t.encode()) for t in clip_keyterm_library(big)) <= 2 * 1024 * 1024


def test_session_timeline_is_position_in_recording():
    tl = SessionTimeline()
    tl.start_session()
    for _ in range(10):  # 1 с звука подряд
        tl.on_real_sent(0.1)
        tl.advance_recorded(0.1)
    assert tl.to_meeting(0.5) == pytest.approx(0.5)
    # новая сессия: 5 с накопленного в очереди звука выброшены как устаревшие (но записаны)
    tl.start_session()
    tl.advance_recorded(5.0)
    tl.on_real_sent(0.1)
    tl.advance_recorded(0.1)
    assert tl.to_meeting(0.05) == pytest.approx(6.05)
    # служебная тишина идёт в сессию, но не в запись
    tl.on_silence_sent(0.1)
    tl.on_real_sent(0.1)
    tl.advance_recorded(0.1)
    assert tl.to_meeting(0.25) == pytest.approx(6.15)
