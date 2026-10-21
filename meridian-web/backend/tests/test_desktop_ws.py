# -*- coding: utf-8 -*-
"""WebSocket десктоп-приложения: /ws/desktop/meetings/{id}?token=<токен устройства>.

Сокет подключает приложение к общей MeetingRoom без аудио: готовые фразы сохраняются тем же
upsert, что и REST, попадают в историю комнаты как финальные сегменты STT и питают подсказки.

TestClient (синхронные тесты): приложение крутится в своём цикле событий, поэтому БД — файловый
SQLite без пула (каждая сессия — своё соединение), а LLM подменён заглушкой. Приложение
собирается из одних WS-роутеров, без lifespan основного приложения.
"""

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.websockets import WebSocketDisconnect

import app.database as database
from app.auth.service import create_access_token, hash_password
from app.database import Base
from app.logging_setup import RedactionFilter, setup_logging
from app.models.desktop import DesktopDevice
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.user import User
from app.services import desktop_sync as sync
from app.services import session_manager as sm_mod
from app.services.desktop_devices import enroll_device, revoke_device
from app.services.meeting_room import room_registry
from app.services.session_manager import SessionManager
from app.ws import desktop_handler
from app.ws.desktop_handler import router as desktop_ws_router
from app.ws.handler import router as web_ws_router

STARTED = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)

CARDS = json.dumps({"cards": [{
    "type": "clarify", "priority": 3, "title": "Уточнить сроки", "text": "Уточните срок поставки.",
    "why": "Срок не назван.", "evidence": [], "confidence": 0.7,
}]}, ensure_ascii=False)


class FakeLLM:
    model = "fake-model"

    def __init__(self):
        self.prompts: list[str] = []

    async def get_suggestion_async(self, prompt, max_tokens=None):
        self.prompts.append(prompt)
        return CARDS


def _run(coro):
    return asyncio.run(coro)


class Env:
    def __init__(self, sm, client, llm):
        self.sm = sm
        self.client = client
        self.llm = llm

    # --- данные ---

    def user(self, email="eng@test.local", active=True) -> User:
        async def go():
            async with self.sm() as db:
                u = User(email=email, password_hash=hash_password("x"), role="user", is_active=active)
                db.add(u)
                await db.commit()
                return u
        return _run(go())

    def device(self, user: User) -> tuple[int, str]:
        async def go():
            async with self.sm() as db:
                dev, token = await enroll_device(db, user.id, "Рабочий ПК", "windows", "0.1.0")
                await db.commit()
                return dev.id, token
        return _run(go())

    def meeting(self, user: User, mode="online") -> int:
        async def go():
            async with self.sm() as db:
                dev = (await db.execute(select(DesktopDevice).where(DesktopDevice.user_id == user.id))
                       ).scalars().first()
                meeting, _ = await sync.upsert_meeting(
                    db, user.id, dev.id, str(uuid.uuid4()), title="Планерка", started_at=STARTED,
                    ended_at=None, capture_mode=mode, customer_id=None, object_id=None)
                await db.commit()
                return meeting.id
        return _run(go())

    def revoke(self, device_id: int) -> None:
        async def go():
            async with self.sm() as db:
                await revoke_device(db, await db.get(DesktopDevice, device_id))
                await db.commit()
        _run(go())

    def set_status(self, meeting_id: int, status: str) -> None:
        async def go():
            async with self.sm() as db:
                (await db.get(MeetingSession, meeting_id)).status = status
                await db.commit()
        _run(go())

    def meeting_row(self, meeting_id: int) -> MeetingSession:
        async def go():
            async with self.sm() as db:
                return await db.get(MeetingSession, meeting_id)
        return _run(go())

    def segments(self, meeting_id: int) -> list[TranscriptSegmentRecord]:
        async def go():
            async with self.sm() as db:
                return list((await db.execute(
                    select(TranscriptSegmentRecord)
                    .where(TranscriptSegmentRecord.session_id == meeting_id)
                    .order_by(TranscriptSegmentRecord.start_time)
                )).scalars().all())
        return _run(go())

    def count_segments(self, meeting_id: int) -> int:
        async def go():
            async with self.sm() as db:
                return (await db.execute(
                    select(func.count()).select_from(TranscriptSegmentRecord)
                    .where(TranscriptSegmentRecord.session_id == meeting_id))).scalar_one()
        return _run(go())

    def ws(self, meeting_id: int, token: str, *, last: bool = True):
        return _Session(self, meeting_id, token, last)


class _Session:
    """websocket_connect + ожидание конца обработчика при выходе.

    TestClient сразу после disconnect отменяет задачу приложения, и уборка в finally
    (выход из комнаты, возврат is_active) обрывалась бы на первом реальном await.
    В бою сервер задачу не отменяет, поэтому ждём завершения сами.
    """

    def __init__(self, env: "Env", meeting_id: int, token: str, last: bool):
        self._meeting_id = meeting_id
        self._last = last  # False — рядом держится другой сокет этой встречи, ждать release нечего
        self._cm = env.client.websocket_connect(f"/ws/desktop/meetings/{meeting_id}?token={token}")

    def __enter__(self):
        self._ws = self._cm.__enter__()
        return self._ws

    def __exit__(self, *args):
        self._ws.close()
        if self._last:
            _wait(lambda: self._meeting_id not in desktop_handler._live, 5)
        time.sleep(0.1)
        return self._cm.__exit__(*args)


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/ws.db", poolclass=NullPool)

    async def create():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
    _run(create())
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Боевая фабрика сессий импортирована в десятки модулей по имени — подменяем везде.
    original = database.async_session
    for name, mod in list(sys.modules.items()):
        if name.startswith("app.") and getattr(mod, "async_session", None) is original:
            monkeypatch.setattr(mod, "async_session", sm)
    monkeypatch.setattr(database, "async_session", sm)

    llm = FakeLLM()
    real_get = room_registry.get_or_create_room

    async def get_room(meeting_id):
        room = await real_get(meeting_id)
        if room.session.llm_client is None:
            room.session.llm_client = llm
        return room

    monkeypatch.setattr(room_registry, "get_or_create_room", get_room)
    monkeypatch.setattr(room_registry, "_rooms", {})
    monkeypatch.setattr(room_registry, "_locks", {})
    monkeypatch.setattr(desktop_handler, "_live", {})
    monkeypatch.setattr(desktop_handler, "_live_lock", asyncio.Lock())

    app = FastAPI()
    app.include_router(desktop_ws_router)
    app.include_router(web_ws_router)
    with TestClient(app) as client:  # один цикл событий на все сокеты теста
        yield Env(sm, client, llm)
    _run(engine.dispose())


def _setup(env: Env, mode="online"):
    user = env.user()
    device_id, token = env.device(user)
    meeting_id = env.meeting(user, mode)
    return user, device_id, token, meeting_id


def _seg(cid, text, start, channel="mic", **kw) -> dict:
    return {"client_segment_id": cid, "text": text, "start_time": start, "end_time": start + 1.5,
            "channel": channel, "wall_clock": datetime.now(timezone.utc).isoformat(), **kw}


def _recv_until(ws, msg_type: str, limit: int = 40) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"не дождались {msg_type}")


def _send_segments(ws, *segments) -> dict:
    ws.send_json({"type": "transcript_segments", "segments": list(segments)})
    return _recv_until(ws, "segments_ack")


def _wait(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _expect_close(env: Env, meeting_id: int, token: str, code: int) -> dict:
    with env.ws(meeting_id, token) as ws:
        err = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == code
    return err


# ---------- доступ ----------

def test_bad_missing_and_revoked_token_closed_4401(env):
    _, device_id, token, meeting_id = _setup(env)
    err = _expect_close(env, meeting_id, "no-such-token", 4401)
    assert err["type"] == "error" and err["code"] == "unauthorized"
    _expect_close(env, meeting_id, "", 4401)
    env.revoke(device_id)
    _expect_close(env, meeting_id, token, 4401)


def test_inactive_user_closed_4401(env):
    user = env.user(active=False)
    _, token = env.device(user)
    # встреча чужая/несуществующая не важна: токен не принимается раньше
    _expect_close(env, 1, token, 4401)


def test_foreign_or_missing_meeting_closed_4404(env):
    _, _, token, meeting_id = _setup(env)
    other = env.user("other@test.local")
    env.device(other)
    foreign = env.meeting(other)
    assert _expect_close(env, foreign, token, 4404)["code"] == "meeting_not_found"
    _expect_close(env, meeting_id + 999, token, 4404)


def test_finalized_meeting_closed_4409(env):
    _, _, token, meeting_id = _setup(env)
    env.set_status(meeting_id, "finalized")
    assert _expect_close(env, meeting_id, token, 4409)["code"] == "meeting_closed"


def test_revoked_during_session_rejects_next_message(env):
    _, device_id, token, meeting_id = _setup(env)
    with env.ws(meeting_id, token) as ws:
        _send_segments(ws, _seg("a", "Добрый день", 0))
        env.revoke(device_id)
        ws.send_json({"type": "transcript_segments", "segments": [_seg("b", "Ещё фраза", 2)]})
        assert _recv_until(ws, "error")["code"] == "unauthorized"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401
    assert env.count_segments(meeting_id) == 1  # вторая фраза не принята


# ---------- сегменты ----------

def test_segments_saved_with_sides_and_resend_does_not_duplicate(env):
    _, _, token, meeting_id = _setup(env)
    batch = [
        _seg("s1", "Добрый день, начнём", 0, "mic"),
        _seg("s2", "Слушаю вас", 2, "system"),
        _seg("s3", "Общий звук", 4, "mixed", speaker_label="Иван"),
    ]
    with env.ws(meeting_id, token) as ws:
        ack = _send_segments(ws, *batch)
        assert ack["created"] == 3 and ack["updated"] == 0
        assert ack["client_segment_ids"] == ["s1", "s2", "s3"]
        # повтор (как после обрыва сети): тот же id, тот же текст
        ack2 = _send_segments(ws, *batch)
        assert ack2["created"] == 0 and ack2["updated"] == 3
        room = room_registry.get_room(meeting_id)
        assert [s.text for s in room.session.committed_segments] == [
            "Добрый день, начнём", "Слушаю вас", "Общий звук"]

    rows = env.segments(meeting_id)
    assert len(rows) == 3
    assert [(r.speaker_id, r.speaker_label, r.origin) for r in rows] == [
        ("desktop_mic", "Мы", "desktop"),
        ("desktop_system", "Оппонент", "desktop"),
        ("desktop_mixed", "Иван", "desktop"),
    ]
    # комната опустела и сохранила сегменты: дубля с серверным id не появилось
    assert env.count_segments(meeting_id) == 3


def test_segments_land_in_room_history_with_side(env):
    _, _, token, meeting_id = _setup(env)
    with env.ws(meeting_id, token) as ws:
        _send_segments(ws, _seg("s1", "Предлагаем скидку пять процентов", 0, "mic"),
                       _seg("s2", "Нужна скидка десять", 2, "system"),
                       _seg("s3", "Подумаем", 4, "mixed"))
        session = room_registry.get_room(meeting_id).session
        segments = session.committed_segments
        server_id = sync.segment_server_id(
            _client_uuid(env, meeting_id), "s1")
        assert segments[0].segment_id == server_id
        assert [(s.speaker_id, s.speaker_label) for s in segments] == [
            ("desktop_mic", "Мы"), ("desktop_system", "Оппонент"), ("desktop_mixed", "Speaker_1")]
        assert [t.side for t in session.turns] == ["self", "opponent", None]
        context = session._get_committed_context()
        assert "Мы [МЫ]: Предлагаем скидку" in context
        assert "Оппонент [НЕ МЫ]: Нужна скидка" in context
        assert "Speaker_1: Подумаем" in context  # mixed — без стороны
        assert session.speaker_roles["Мы"] == "self" and session.speaker_roles["Оппонент"] == "opponent"


def _client_uuid(env: Env, meeting_id: int) -> str:
    async def go():
        async with env.sm() as db:
            from app.models.desktop import DesktopMeetingLink
            return (await db.execute(select(DesktopMeetingLink.client_uuid).where(
                DesktopMeetingLink.meeting_id == meeting_id))).scalar_one()
    return _run(go())


def test_in_person_meeting_gets_roles_for_channels(env):
    _, _, token, meeting_id = _setup(env, mode="in_person")
    with env.ws(meeting_id, token) as ws:
        _send_segments(ws, _seg("s1", "Здравствуйте", 0, "mic"))
        assert room_registry.get_room(meeting_id).session.speaker_roles == {"Мы": "self"}
    from app.models.meeting_conversation import MeetingSpeakerRole

    async def roles():
        async with env.sm() as db:
            return {(r.speaker_label, r.side) for r in (await db.execute(select(MeetingSpeakerRole))).scalars()}
    assert ("Мы", "self") in _run(roles())


def test_invalid_segments_payload_gives_error_and_keeps_socket(env):
    _, _, token, meeting_id = _setup(env)
    with env.ws(meeting_id, token) as ws:
        ws.send_json({"type": "transcript_segments", "segments": [{"text": "без id"}]})
        assert _recv_until(ws, "error")["code"] == "invalid_segments"
        ws.send_json({"type": "ping"})
        assert _recv_until(ws, "pong")


def test_echo_to_web_client_in_same_room(env):
    user, _, token, meeting_id = _setup(env)
    jwt = create_access_token(user.id, user.role)
    with env.client.websocket_connect(f"/ws/meetings/{meeting_id}?token={jwt}&device_role=viewer") as web:
        with env.ws(meeting_id, token) as ws:
            _send_segments(ws, _seg("s1", "Давайте обсудим сроки", 0, "system"))
            msg = _recv_until(web, "committed_transcript")
            assert msg["speaker"] == "Оппонент" and msg["text"] == "Давайте обсудим сроки"
            turn = _recv_until(web, "turn_update")
            assert turn["speaker"] == "Оппонент"


def test_reconnect_hydrates_fresh_room_without_rebroadcast_or_hints(env, monkeypatch):
    _, _, token, meeting_id = _setup(env)
    scheduled: list[str] = []
    real = SessionManager._schedule_hint_check
    monkeypatch.setattr(SessionManager, "_schedule_hint_check",
                        lambda self, seg: (scheduled.append(seg.segment_id), real(self, seg))[1])
    batch = [_seg("s1", "Первая фраза", 0, "mic"), _seg("s2", "Вторая фраза", 2, "system")]
    with env.ws(meeting_id, token) as ws:
        _send_segments(ws, *batch)
    assert len(scheduled) == 2
    assert _wait(lambda: room_registry.get_room(meeting_id) is None)  # комната освобождена

    with env.ws(meeting_id, token) as ws:
        ws.send_json({"type": "ping"})
        _recv_until(ws, "pong")  # к этому моменту комната создана и досыпана
        session = room_registry.get_room(meeting_id).session
        assert [s.text for s in session.committed_segments] == ["Первая фраза", "Вторая фраза"]
        assert [t.side for t in session.turns] == ["self", "opponent"]
        ack = _send_segments(ws, *batch)  # приложение не знало, что ack дошёл
        assert ack["created"] == 0
        assert len(session.committed_segments) == 2  # дубля в истории нет
    assert len(scheduled) == 2  # и подсказки по старым фразам не запускались
    assert env.count_segments(meeting_id) == 2


def test_auto_hint_check_runs_for_text_segments_once(env, monkeypatch):
    _, _, token, meeting_id = _setup(env)
    calls: list[tuple[str, str]] = []

    async def fake_flow(self, text, recent, doc_context, source_method="", ctx=None):
        calls.append((text, recent))
        return True

    monkeypatch.setattr(SessionManager, "_signal_flow", fake_flow)
    monkeypatch.setattr(sm_mod, "HINT_DEBOUNCE_SEC", 0.05)
    batch = [_seg("s1", "Срок поставки сорок дней", 0, "system"),
             _seg("s2", "Нас это не устраивает", 2, "mic")]
    with env.ws(meeting_id, token) as ws:
        _send_segments(ws, *batch)
        assert _wait(lambda: len(calls) == 1)
        text, recent = calls[0]
        assert "Срок поставки сорок дней" in text and "Нас это не устраивает" in text
        assert "Оппонент [НЕ МЫ]" in recent and "Мы [МЫ]" in recent
        # повтор тех же фраз не запускает проверку заново
        _send_segments(ws, *batch)
        time.sleep(0.4)
        assert len(calls) == 1


# ---------- подсказки и служебное ----------

def test_request_suggestion_calls_llm_and_client_gets_suggestion(env):
    _, _, token, meeting_id = _setup(env)
    with env.ws(meeting_id, token) as ws:
        _send_segments(ws, _seg("s1", "Срок поставки сорок дней", 0, "system"),
                       _seg("s2", "Нас это не устраивает", 2, "mic"))
        ws.send_json({"type": "request_suggestion"})
        loading = _recv_until(ws, "suggestion_loading")
        assert loading["loading"] is True
        suggestion = _recv_until(ws, "suggestion")
        assert "Уточните срок поставки" in suggestion["text"]
        assert suggestion["is_auto"] is False
        assert env.llm.prompts and "Срок поставки сорок дней" in env.llm.prompts[0]


def test_strengthen_position_goes_to_room_dispatcher(env, monkeypatch):
    _, _, token, meeting_id = _setup(env)
    called: list[int] = []

    async def fake_strengthen(self):
        called.append(1)
        await self._send_json({"type": "strengthen_loading", "loading": False})

    monkeypatch.setattr(SessionManager, "strengthen_position", fake_strengthen)
    with env.ws(meeting_id, token) as ws:
        ws.send_json({"type": "strengthen_position"})
        assert _recv_until(ws, "strengthen_loading")["loading"] is False
    assert called == [1]


def test_ping_pong(env):
    _, _, token, meeting_id = _setup(env)
    with env.ws(meeting_id, token) as ws:
        ws.send_json({"type": "ping", "ts": 123})
        assert _recv_until(ws, "pong") == {"type": "pong", "ts": 123}


def test_audio_and_unknown_messages_rejected(env):
    _, _, token, meeting_id = _setup(env)
    with env.ws(meeting_id, token) as ws:
        ws.send_bytes(b"\x00\x01" * 100)
        assert _recv_until(ws, "error")["code"] == "audio_not_supported"
        ws.send_json({"type": "start_listening"})
        assert _recv_until(ws, "error")["code"] == "audio_not_supported"
        ws.send_json({"type": "finalize_meeting"})
        assert _recv_until(ws, "error")["code"] == "unsupported_type"
        ws.send_text("не json")
        assert _recv_until(ws, "error")["code"] == "invalid_json"
        session = room_registry.get_room(meeting_id).session
        assert session.is_listening is False
    assert env.meeting_row(meeting_id).status == "active"  # встречу сокет не финализирует


# ---------- is_active ----------

def test_is_active_true_while_connected_and_restored_after(env):
    _, _, token, meeting_id = _setup(env)
    assert env.meeting_row(meeting_id).is_active is False
    with env.ws(meeting_id, token) as first:
        first.send_json({"type": "ping"})
        _recv_until(first, "pong")
        assert env.meeting_row(meeting_id).is_active is True
        with env.ws(meeting_id, token, last=False) as second:
            second.send_json({"type": "ping"})
            _recv_until(second, "pong")
        # один сокет ушёл, второй держит встречу живой
        time.sleep(0.2)
        assert env.meeting_row(meeting_id).is_active is True
    assert _wait(lambda: env.meeting_row(meeting_id).is_active is False)
    row = env.meeting_row(meeting_id)
    assert row.status == "active" and row.ended_at is None


def test_is_active_not_touched_if_meeting_finalized_meanwhile(env):
    _, _, token, meeting_id = _setup(env)
    with env.ws(meeting_id, token) as ws:
        ws.send_json({"type": "ping"})
        _recv_until(ws, "pong")
        env.set_status(meeting_id, "finalized")  # приложение финализировало по REST
        ws.send_json({"type": "transcript_segments", "segments": [_seg("late", "Поздняя фраза", 9)]})
        assert _recv_until(ws, "error")["code"] == "meeting_closed"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4409
    assert env.count_segments(meeting_id) == 0


# ---------- токен в логах ----------

def test_uvicorn_error_log_redacts_device_token():
    setup_logging()
    uv = logging.getLogger("uvicorn.error")
    assert any(isinstance(f, RedactionFilter) for f in uv.filters)
    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 1, '%s - "WebSocket %s" [accepted]',
        ("127.0.0.1:5000", "/ws/desktop/meetings/7?token=SECRET-device-token"), None)
    assert uv.filter(record)
    assert "SECRET-device-token" not in record.getMessage()
    assert "token=***" in record.getMessage()



def test_reset_stale_live_flags_only_touches_desktop_meetings(env):
    """После рестарта is_active снимается только у встреч приложения."""
    from app.services.desktop_sync import reset_stale_live_flags

    user, _, _, desk_id = _setup(env)

    async def go():
        async with env.sm() as db:
            web = MeetingSession(user_id=user.id, title="web", is_active=True)
            db.add(web)
            (await db.get(MeetingSession, desk_id)).is_active = True
            await db.commit()
            n = await reset_stale_live_flags(db)
            return n, (await db.get(MeetingSession, web.id)).is_active, \
                (await db.get(MeetingSession, desk_id)).is_active
    assert _run(go()) == (1, True, False)
