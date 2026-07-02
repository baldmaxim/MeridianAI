"""Этап 16: handle_audio_frame routes MAUD2 v2 → shadow ingest, legacy → STT path."""

import array

from types import SimpleNamespace

from app.core.context.audio_frame_v2 import build_audio_frame_v2
from app.services.meeting_room import MeetingRoom

_handle = MeetingRoom.handle_audio_frame  # unbound


def _v2_frame():
    h = dict(protocol_version=2, sequence=1, sample_rate=16000, channels=2, codec="pcm16",
             layout="interleaved", route="usb_recorder", capture_pipeline="multichannel_shadow_stream")
    return build_audio_frame_v2(h, array.array("h", (1000, -1000, 2000, -2000)).tobytes())


class _Queue:
    def __init__(self):
        self.items = []

    async def put(self, x):
        self.items.append(x)


def _fake_room(*, v2_calls, listening=True):
    session = SimpleNamespace(
        ingest_audio_frame_v2_shadow=lambda data: v2_calls.append(data) or True,
        is_listening=listening,
        audio_queue=_Queue(),
        touch=lambda: None,
    )

    async def _noop_tap(_cid, _data):
        return None

    return SimpleNamespace(
        session=session,
        connections={"c1": SimpleNamespace(device_role="primary", clock=None)},
        active_audio_source="c1",
        audio_recorder=SimpleNamespace(append=lambda data: None),
        ingest=SimpleNamespace(enabled=False),
        _tap_primary_ingest=_noop_tap,
    )


async def test_v2_frame_routed_to_shadow_not_stt():
    v2_calls = []
    room = _fake_room(v2_calls=v2_calls)
    await _handle(room, "c1", _v2_frame())
    assert len(v2_calls) == 1                  # ушло в shadow ingest
    assert room.session.audio_queue.items == []  # НЕ в legacy STT очередь


async def test_legacy_frame_goes_to_stt_not_shadow():
    v2_calls = []
    room = _fake_room(v2_calls=v2_calls)
    legacy = array.array("h", (5, -5) * 800).tobytes()  # 1600 семплов mono PCM, не MAUD2
    await _handle(room, "c1", legacy)
    assert v2_calls == []                       # shadow не дёргался
    assert len(room.session.audio_queue.items) == 1  # ушло в legacy STT


async def test_v2_parse_error_does_not_break_legacy_path():
    # сломанный v2 (правильная магия, битый заголовок) — ingest вернёт False, но handle_audio_frame
    # всё равно вернётся без исключения и не тронет legacy очередь
    v2_calls = []

    def _ingest(data):
        v2_calls.append(data)
        return False  # имитируем parse error внутри session

    room = _fake_room(v2_calls=v2_calls)
    room.session.ingest_audio_frame_v2_shadow = _ingest
    bad_v2 = b"MAUD2" + b"\x00\x05" + b"{bad}" + b"\x00\x00"
    await _handle(room, "c1", bad_v2)
    assert len(v2_calls) == 1
    assert room.session.audio_queue.items == []  # не попало в STT, legacy не сломан
