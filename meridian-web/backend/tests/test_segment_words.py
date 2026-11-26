# -*- coding: utf-8 -*-
"""Пословные таймкоды сегментов: разбор words_json, раздача слов батча, GET /api/meetings/{id}."""

import json
from datetime import datetime

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.database import Base, get_db
from app.models.batch_job import BatchJob
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.user import User
from app.services.segment_words import assign_batch_words, parse_words_json


def test_parse_words_json_keeps_only_words():
    raw = json.dumps([
        {"text": "Привет", "start": 0.0, "end": 0.4, "type": "word", "logprob": -0.1},
        {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
        {"text": ",", "start": 0.5, "end": 0.5, "type": "punctuation"},
        {"text": "мир", "start": 0.5, "end": 0.9},
        {"text": "   ", "start": 1.0, "end": 1.1, "type": "word"},
        {"text": "без", "start": "1", "end": 1.2, "type": "word"},
        {"text": "булево", "start": True, "end": 1.2},
        "мусор",
    ])
    assert parse_words_json(raw) == [
        {"text": "Привет", "start": 0.0, "end": 0.4},
        {"text": "мир", "start": 0.5, "end": 0.9},
    ]


def test_parse_words_json_bad_input():
    assert parse_words_json(None) is None
    assert parse_words_json("") is None
    assert parse_words_json("{не json") is None
    assert parse_words_json('{"a": 1}') is None
    assert parse_words_json("[]") is None
    assert parse_words_json('[{"text": " ", "start": 0, "end": 1, "type": "spacing"}]') is None


def _w(text, start, end):
    return {"text": text, "start": start, "end": end, "speaker_id": "A"}


def test_assign_batch_words_boundaries_and_no_duplicates():
    words = [_w("a", 0.0, 0.5), _w("b", 1.0, 1.5), _w("c", 2.02, 2.5), _w("d", 3.0, 3.5), _w("e", 9.0, 9.5)]
    # сегмент 1: [0, 2.0], сегмент 2: [2.0, 3.5] — слово c (2.02) в eps обоих, достаётся первому
    res = assign_batch_words([(0.0, 2.0), (2.0, 3.5), (5.0, 6.0)], words)
    assert [w["text"] for w in res[0]] == ["a", "b", "c"]
    assert [w["text"] for w in res[1]] == ["d"]
    assert res[2] is None
    assert set(res[0][0]) == {"text", "start", "end"}


def test_assign_batch_words_eps_edges():
    words = [_w("x", 0.95, 1.0), _w("y", 2.05, 2.1), _w("z", 2.06, 2.1)]
    res = assign_batch_words([(1.0, 2.0)], words, eps=0.05)
    assert [w["text"] for w in res[0]] == ["x", "y"]


def test_assign_batch_words_keeps_input_order_of_segments():
    words = [_w("a", 0.0, 0.5), _w("b", 10.0, 10.5)]
    res = assign_batch_words([(10.0, 11.0), (0.0, 1.0)], words)
    assert [w["text"] for w in res[0]] == ["b"]
    assert [w["text"] for w in res[1]] == ["a"]


@pytest_asyncio.fixture
async def env():
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        user = User(email="words@t.local", password_hash="x", role="user", is_active=True)
        s.add(user)
        await s.commit()

    async def _db():
        async with sm() as s:
            yield s

    async def _cur():
        return user

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _cur
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield sm, user, c
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def _seg(mid, sid, start, end, origin, words_json=None):
    return TranscriptSegmentRecord(
        session_id=mid, segment_id=sid, text="t", speaker_id="s", start_time=start, end_time=end,
        wall_clock=datetime(2026, 10, 21, 9, 0, int(start)), origin=origin, word_count=1,
        words_json=words_json,
    )


async def _meeting(sm, user) -> int:
    async with sm() as db:
        m = MeetingSession(user_id=user.id, created_by_user_id=user.id, title="Встреча",
                           started_at=datetime(2026, 10, 21, 9, 0), is_active=False)
        db.add(m)
        await db.commit()
        return m.id


async def test_detail_words_from_words_json(env):
    sm, user, c = env
    mid = await _meeting(sm, user)
    raw = json.dumps([{"text": "Добрый", "start": 1.0, "end": 1.4, "type": "word"},
                      {"text": " ", "start": 1.4, "end": 1.5, "type": "spacing"}])
    async with sm() as db:
        db.add(_seg(mid, "live1", 1.0, 2.0, "live", raw))
        db.add(_seg(mid, "live2", 3.0, 4.0, "live"))
        await db.commit()
    r = await c.get(f"/api/meetings/{mid}")
    assert r.status_code == 200
    segs = {s["segment_id"]: s for s in r.json()["segments"]}
    assert segs["live1"]["words"] == [{"text": "Добрый", "start": 1.0, "end": 1.4}]
    assert segs["live2"]["words"] is None


async def _batch_meeting(sm, user, jobs: int):
    mid = await _meeting(sm, user)
    data = {"words": [{"text": "один", "start": 0.0, "end": 0.5, "speaker_id": "A"},
                      {"text": "два", "start": 0.6, "end": 1.0, "speaker_id": "A"},
                      {"text": "три", "start": 5.0, "end": 5.5, "speaker_id": "B"}]}
    async with sm() as db:
        db.add(_seg(mid, "b1", 0.0, 1.0, "batch_finalized"))
        db.add(_seg(mid, "b2", 5.0, 5.5, "batch_finalized"))
        for _ in range(jobs):
            db.add(BatchJob(user_id=user.id, meeting_id=mid, original_filename="rec.mp3",
                            file_path="x", transcription_json=json.dumps(data)))
        await db.commit()
    return mid


async def test_detail_words_from_batch_job(env):
    sm, user, c = env
    mid = await _batch_meeting(sm, user, jobs=1)
    segs = {s["segment_id"]: s for s in (await c.get(f"/api/meetings/{mid}")).json()["segments"]}
    assert [w["text"] for w in segs["b1"]["words"]] == ["один", "два"]
    assert segs["b2"]["words"] == [{"text": "три", "start": 5.0, "end": 5.5}]


async def test_detail_words_ambiguous_batch_gives_none(env):
    sm, user, c = env
    mid = await _batch_meeting(sm, user, jobs=2)
    r = await c.get(f"/api/meetings/{mid}")
    assert r.status_code == 200
    assert all(s["words"] is None for s in r.json()["segments"])


async def test_detail_words_broken_batch_json_does_not_fail(env):
    sm, user, c = env
    mid = await _meeting(sm, user)
    async with sm() as db:
        db.add(_seg(mid, "b1", 0.0, 1.0, "batch_finalized"))
        db.add(BatchJob(user_id=user.id, meeting_id=mid, original_filename="rec.mp3",
                        file_path="x", transcription_json="{битый"))
        await db.commit()
    r = await c.get(f"/api/meetings/{mid}")
    assert r.status_code == 200 and r.json()["segments"][0]["words"] is None
