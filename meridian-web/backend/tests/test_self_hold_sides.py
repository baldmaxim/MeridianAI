"""Калибровка сторон кнопкой «держу — говорим мы» (очная встреча, один микрофон).

Чистый трекер интервалов удержания и интеграция в MeetingRoom (без БД и внешних сервисов).
"""

import asyncio
import time
from datetime import datetime

from app.core.transcription.models import CommittedSegment, TranscriptSegment
from app.services.meeting_room import MeetingRoom, MeetingConnection
from app.services.self_hold_sides import (
    CALIBRATION_TAIL_MS,
    MAX_HOLD_MS,
    OPPONENT_WEIGHT,
    SelfHoldTracker,
)


# ---------- чистый трекер ----------

def test_no_presses_means_no_vote():
    assert SelfHoldTracker().classify(1_000, 3_000) is None


def test_speech_under_hold_is_self():
    t = SelfHoldTracker()
    t.press("c", 10_000)
    t.release("c", 13_000)
    side, weight = t.classify(10_200, 12_800)
    assert side == "self" and weight > 0.9


def test_late_press_and_early_release_still_self():
    t = SelfHoldTracker()
    t.press("c", 10_400)   # нажал с опозданием
    t.release("c", 12_600)  # отпустил чуть раньше конца фразы
    assert t.classify(10_000, 13_000)[0] == "self"


def test_released_inside_calibration_window_is_opponent():
    t = SelfHoldTracker()
    t.press("c", 10_000)
    t.release("c", 12_000)
    assert t.classify(14_000, 17_000) == ("opponent", OPPONENT_WEIGHT)


def test_released_long_after_calibration_gives_no_vote():
    t = SelfHoldTracker()
    t.press("c", 10_000)
    t.release("c", 12_000)
    late = 12_000 + CALIBRATION_TAIL_MS + 5_000
    assert t.classify(late, late + 3_000) is None


def test_mixed_replica_gives_no_vote():
    t = SelfHoldTracker()
    t.press("c", 10_000)
    t.release("c", 11_000)
    assert t.classify(10_000, 15_000) is None  # под кнопкой ~30% реплики


def test_still_held_counts_until_segment_end():
    t = SelfHoldTracker()
    t.press("c", 10_000)  # ещё держит, а сегмент уже зафиксирован
    assert t.classify(10_100, 12_000)[0] == "self"


def test_lost_release_does_not_hold_forever():
    t = SelfHoldTracker()
    t.press("c", 10_000)  # «отпустил» не дошёл
    late = 10_000 + MAX_HOLD_MS + 10_000
    assert t.classify(late, late + 3_000) != ("self", 1.0)
    t.press("c", late)  # новое нажатие закрывает старое ограниченным интервалом
    assert t.intervals == [(10_000, 10_000 + MAX_HOLD_MS)]


def test_overlapping_holds_from_two_connections_not_double_counted():
    t = SelfHoldTracker()
    t.press("a", 10_000)
    t.press("b", 10_000)
    t.release("a", 11_000)
    t.release("b", 11_000)
    assert t.classify(10_000, 14_000) is None  # ~37% с поправками не превращается в 75%


def test_reset_forgets_everything():
    t = SelfHoldTracker()
    t.press("c", 10_000)
    t.release("c", 12_000)
    t.reset()
    assert t.classify(10_000, 12_000) is None


# ---------- интеграция в комнате ----------

def _room_with_recorder() -> tuple[MeetingRoom, MeetingConnection, list]:
    room = MeetingRoom(meeting_id=1, owner_user_id=1, status="active")
    sink: list = []

    async def send(data):
        sink.append(data)

    conn = MeetingConnection(1, 1, "desktop", send, can_record=True)
    room.connections[conn.connection_id] = conn
    return room, conn, sink


def _segment(i: int, label: str, start_ms: int, end_ms: int) -> CommittedSegment:
    seg = CommittedSegment(text=f"реплика {i}", segment_id=f"seg-{i}", speaker_label=label,
                           wall_clock=datetime.now())
    seg.speech_start_ms, seg.speech_end_ms = start_ms, end_ms
    return seg


async def _hold(room: MeetingRoom, conn: MeetingConnection, holding: bool, ts: int) -> None:
    # Без clock sync сервер берёт время приёма — подменяем его через to_server_ms-путь.
    conn.clock = object()
    conn.to_server_ms = lambda x: x
    await room._dispatch_client_message(conn.connection_id,
                                        {"type": "self_hold", "holding": holding, "client_ts_ms": ts})


async def test_held_replicas_assign_self_to_label(monkeypatch):
    room, conn, sink = _room_with_recorder()
    persisted: list = []

    async def fake_persist(label, side, user_id, **kw):
        persisted.append((label, side))

    monkeypatch.setattr(room, "_persist_speaker_role", fake_persist)
    for i in range(3):
        base = 10_000 + i * 10_000
        await _hold(room, conn, True, base)
        await _hold(room, conn, False, base + 3_000)
        await room._apply_self_hold_side(_segment(i, "DG_S0", base + 100, base + 2_900))

    assert room.session.speaker_roles.get("DG_S0") == "self"
    assert persisted == [("DG_S0", "self")]
    assert any(m.get("type") == "speaker_roles_updated" for m in sink)


async def test_released_replicas_assign_opponent(monkeypatch):
    room, conn, _ = _room_with_recorder()

    async def fake_persist(*a, **kw):
        return None

    monkeypatch.setattr(room, "_persist_speaker_role", fake_persist)
    await _hold(room, conn, True, 10_000)
    await _hold(room, conn, False, 12_000)
    for i in range(3):
        base = 14_000 + i * 4_000
        await room._apply_self_hold_side(_segment(i, "DG_S1", base, base + 3_000))

    assert room.session.speaker_roles.get("DG_S1") == "opponent"


async def test_manual_side_is_not_overwritten_by_hold(monkeypatch):
    room, conn, _ = _room_with_recorder()

    async def fake_persist(*a, **kw):
        raise AssertionError("ручная сторона перетёрта кнопкой")

    monkeypatch.setattr(room, "_persist_speaker_role", fake_persist)
    room.session.speaker_roles["DG_S1"] = "self"  # пользователь назначил сам
    await _hold(room, conn, True, 10_000)
    await _hold(room, conn, False, 12_000)
    for i in range(4):
        base = 14_000 + i * 4_000
        await room._apply_self_hold_side(_segment(i, "DG_S1", base, base + 3_000))

    assert room.session.speaker_roles["DG_S1"] == "self"


async def test_viewer_cannot_hold():
    room, _, _ = _room_with_recorder()

    async def send(data):
        return None

    viewer = MeetingConnection(1, 2, "viewer", send, can_record=False)
    room.connections[viewer.connection_id] = viewer
    await room._dispatch_client_message(viewer.connection_id,
                                        {"type": "self_hold", "holding": True, "client_ts_ms": 1})
    assert room._self_hold.first_press_ms is None


async def test_disconnect_closes_open_hold():
    room, conn, _ = _room_with_recorder()
    await _hold(room, conn, True, int(time.time() * 1000) - 2_000)
    await room.remove_connection(conn.connection_id)
    assert room._self_hold.open_presses == {}
    assert len(room._self_hold.intervals) == 1


async def test_reset_clears_only_auto_sides(monkeypatch):
    room, conn, sink = _room_with_recorder()
    persisted: list = []

    async def fake_persist(label, side, user_id, **kw):
        persisted.append((label, side))

    monkeypatch.setattr(room, "_persist_speaker_role", fake_persist)
    room.session.speaker_roles["SM_2"] = "opponent"  # ручное назначение
    for i in range(3):
        base = 10_000 + i * 10_000
        await _hold(room, conn, True, base)
        await _hold(room, conn, False, base + 3_000)
        await room._apply_self_hold_side(_segment(i, "SM_0", base + 100, base + 2_900))
    assert room.session.speaker_roles["SM_0"] == "self"

    sink.clear()
    await room._reset_auto_sides()

    assert "SM_0" not in room.session.speaker_roles
    assert room.session.speaker_roles["SM_2"] == "opponent"
    assert persisted[-1] == ("SM_0", "")
    assert room._self_hold.first_press_ms is None
    assert any(m.get("type") == "speaker_roles_updated" for m in sink)


async def test_legacy_transcript_hook_gets_committed_segment():
    """Deepgram/Speechmatics: хук получает сегмент с id, меткой и временем речи."""
    room, _, _ = _room_with_recorder()
    session = room.session
    got: list = []

    async def hook(segment, role):
        got.append(segment)

    async def ws_send(data):
        return None

    session._committed_hook = hook
    session._ws_send = ws_send
    session.listening_started_server_ms = 1_000_000
    session._on_legacy_transcript(
        TranscriptSegment(speaker="DG_S0", text="Обсудим сроки", start_time=2.0, end_time=4.5,
                          timestamp=datetime.now()),
        is_partial=False,
    )
    await asyncio.sleep(0)

    assert len(got) == 1
    seg = got[0]
    assert isinstance(seg, CommittedSegment)
    assert seg.segment_id and seg.speaker_label == "DG_S0"
    assert (seg.speech_start_ms, seg.speech_end_ms) == (1_002_000, 1_004_500)
    assert session._committed_segments[-1] is seg
