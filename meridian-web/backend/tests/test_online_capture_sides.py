"""Сторона реплики по источнику звука онлайн-встречи.

Микрофон = наша сторона, звук вкладки/экрана = сторона оппонента. Проверяем чистый
«голосователь» и интеграцию в MeetingRoom (без БД и без внешних сервисов).
"""

from datetime import datetime, timedelta

import pytest

from app.core.transcription.models import CommittedSegment
from app.services.meeting_room import MeetingRoom, MeetingConnection
from app.services.online_capture_sides import (
    HINT_SOURCE,
    OnlineCaptureSideVoter,
    clamp_level,
    virtual_device_ids,
)


# ---------- чистый голосователь ----------

def test_voter_waits_for_min_votes():
    v = OnlineCaptureSideVoter(min_votes=3, min_ratio=0.75)
    assert v.record("SM_0", "opponent", 0.9) is None
    assert v.record("SM_0", "opponent", 0.9) is None
    assert v.record("SM_0", "opponent", 0.9) == "opponent"


def test_voter_decides_once_per_speaker():
    v = OnlineCaptureSideVoter(min_votes=2, min_ratio=0.7)
    v.record("SM_1", "self", 1.0)
    assert v.record("SM_1", "self", 1.0) == "self"
    assert v.record("SM_1", "self", 1.0) is None  # повторно БД/UI не дёргаем


def test_voter_silent_while_sides_are_mixed():
    """Спикер звучит то в микрофоне, то в захвате встречи — сторона не назначается."""
    v = OnlineCaptureSideVoter(min_votes=3, min_ratio=0.75)
    v.record("SM_2", "self", 1.0)
    v.record("SM_2", "opponent", 1.0)
    assert v.record("SM_2", "self", 1.0) is None


def test_voter_forget_returns_speaker_to_manual_control():
    v = OnlineCaptureSideVoter(min_votes=1, min_ratio=0.5)
    assert v.record("SM_3", "opponent", 1.0) == "opponent"
    assert v.is_auto_assigned("SM_3") is True
    v.forget("SM_3")
    assert v.is_auto_assigned("SM_3") is False


@pytest.mark.parametrize("raw,expected", [
    (0.4, 0.4), (-1, 0.0), (5, 1.0), ("нет", 0.0), (None, 0.0), (float("nan"), 0.0),
])
def test_clamp_level_survives_untrusted_json(raw, expected):
    assert clamp_level(raw) == expected


def test_virtual_device_ids_are_distinct():
    a, b = virtual_device_ids("conn-1")
    assert a != b and a.startswith("conn-1") and b.startswith("conn-1")


# ---------- интеграция в комнате ----------

def _room_with_recorder() -> tuple[MeetingRoom, MeetingConnection, list]:
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    sink: list = []

    async def send(data):
        sink.append(data)

    conn = MeetingConnection(1, 1, "desktop", send, can_record=True)
    room.connections[conn.connection_id] = conn
    return room, conn, sink


def _levels(mic: float, system: float, active: bool = True) -> dict:
    return {
        "type": "audio_source_levels",
        "mic_rms": mic, "mic_peak": mic,
        "system_rms": system, "system_peak": system,
        "system_active": active, "seq": 1,
    }


def test_levels_register_two_virtual_devices():
    room, conn, _ = _room_with_recorder()
    room._handle_audio_source_levels(conn.connection_id, _levels(0.2, 0.0), 1000)
    self_id, opponent_id = virtual_device_ids(conn.connection_id)
    assert set(room.observer.devices) == {self_id, opponent_id}
    assert room.observer.devices[self_id].side_hint == "self"
    assert room.observer.devices[opponent_id].side_hint == "opponent"


def test_mic_only_recording_does_not_create_side_devices():
    """Очная встреча (захват экрана выключен) не должна получать сторону «мы» на пустом месте."""
    room, conn, _ = _room_with_recorder()
    room._handle_audio_source_levels(conn.connection_id, _levels(0.3, 0.0, active=False), 1000)
    assert room.observer.devices == {}


def test_devices_removed_when_screen_sharing_stops():
    room, conn, _ = _room_with_recorder()
    room._handle_audio_source_levels(conn.connection_id, _levels(0.2, 0.3), 1000)
    assert room.observer.devices
    room._handle_audio_source_levels(conn.connection_id, _levels(0.2, 0.0, active=False), 1200)
    assert room.observer.devices == {}
    assert conn.connection_id not in room._online_capture_conns


async def test_loud_meeting_audio_marks_segment_as_opponent():
    room, conn, sink = _room_with_recorder()
    for _ in range(6):
        room._handle_audio_source_levels(conn.connection_id, _levels(0.005, 0.30), 1000)

    segment = CommittedSegment(text="Дайте скидку 10%", speaker_label="SM_0",
                               wall_clock=datetime.now())
    await room._broadcast_side_hint(segment)

    hints = [m for m in sink if m.get("type") == "segment_side_hint"]
    assert len(hints) == 1
    assert hints[0]["side"] == "opponent"
    assert hints[0]["source"] == HINT_SOURCE
    assert hints[0]["auto_apply"] is True


async def test_loud_microphone_marks_segment_as_our_side():
    room, conn, sink = _room_with_recorder()
    for _ in range(6):
        room._handle_audio_source_levels(conn.connection_id, _levels(0.30, 0.004), 1000)

    await room._broadcast_side_hint(
        CommittedSegment(text="Мы готовы обсудить сроки", speaker_label="SM_1",
                         wall_clock=datetime.now()))

    hints = [m for m in sink if m.get("type") == "segment_side_hint"]
    assert hints and hints[0]["side"] == "self"


async def test_side_is_assigned_to_speaker_after_enough_hints(monkeypatch):
    room, conn, sink = _room_with_recorder()
    persisted: list = []

    async def fake_persist(label, side, user_id, **kw):
        persisted.append((label, side))

    monkeypatch.setattr(room, "_persist_speaker_role", fake_persist)
    for _ in range(4):
        room._handle_audio_source_levels(conn.connection_id, _levels(0.004, 0.30), 1000)

    for i in range(3):
        await room._broadcast_side_hint(
            CommittedSegment(text=f"реплика {i}", segment_id=f"seg-{i}",
                             speaker_label="SM_0", wall_clock=datetime.now()))

    assert room.session.speaker_roles.get("SM_0") == "opponent"
    assert persisted == [("SM_0", "opponent")]
    assert any(m.get("type") == "speaker_roles_updated" for m in sink)


async def test_manual_side_is_never_overwritten(monkeypatch):
    room, conn, _ = _room_with_recorder()

    async def fake_persist(*a, **kw):
        raise AssertionError("ручное назначение стороны перетёрто авто-определением")

    monkeypatch.setattr(room, "_persist_speaker_role", fake_persist)
    room.session.speaker_roles["SM_0"] = "self"  # пользователь назначил сам

    for _ in range(4):
        room._handle_audio_source_levels(conn.connection_id, _levels(0.004, 0.30), 1000)
    for i in range(4):
        await room._broadcast_side_hint(
            CommittedSegment(text="x", segment_id=f"m-{i}", speaker_label="SM_0",
                             wall_clock=datetime.now()))

    assert room.session.speaker_roles["SM_0"] == "self"


async def test_stale_levels_outside_window_give_no_hint():
    """Метрики старше окна не должны «озвучивать» тишину."""
    room, conn, sink = _room_with_recorder()
    for _ in range(4):
        room._handle_audio_source_levels(conn.connection_id, _levels(0.004, 0.30), 1000)

    future = datetime.now() + timedelta(seconds=30)
    await room._broadcast_side_hint(
        CommittedSegment(text="поздняя реплика", speaker_label="SM_0", wall_clock=future))

    assert not [m for m in sink if m.get("type") == "segment_side_hint"]


async def test_observer_phone_in_room_disables_auto_apply(monkeypatch):
    """Если в комнате есть observer-телефон, подсказка могла прийти от него — не авто-применяем."""
    room, conn, sink = _room_with_recorder()

    async def fake_persist(*a, **kw):
        raise AssertionError("авто-применение сработало при подключённом observer-телефоне")

    monkeypatch.setattr(room, "_persist_speaker_role", fake_persist)
    room.observer.register_device("phone-conn", 1, "observer", side_hint="opponent")
    for _ in range(4):
        room._handle_audio_source_levels(conn.connection_id, _levels(0.004, 0.30), 1000)
    for i in range(3):
        await room._broadcast_side_hint(
            CommittedSegment(text="x", segment_id=f"p-{i}", speaker_label="SM_0",
                             wall_clock=datetime.now()))

    hints = [m for m in sink if m.get("type") == "segment_side_hint"]
    assert hints and hints[0]["source"] == "observer"
    assert hints[0]["auto_apply"] is False
