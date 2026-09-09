# -*- coding: utf-8 -*-
"""Диктофонная запись → встреча со структурным протоколом.

Раньше запись оставалась «батчем»: markdown-протокол внутри задачи был, а решений,
поручений, рисков и кандидатов в базу знаний — нет (на проде 0/0/0/0 за всё время),
потому что их наполняет только финализация встречи.

Заодно закрывает слияние офлайн-дозаписи, которое было без тестов.
"""

import json

import pytest
from sqlalchemy import select

from app.models.batch_job import BatchJob
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.user import User
from app.services.batch_to_meeting import (
    BatchToMeetingError,
    create_meeting_from_batch,
    merge_transcription_into_meeting,
    transcription_segments,
)

WORDS = [
    {"text": "Мы", "start": 0.0, "end": 0.2, "speaker": "Speaker_0", "type": "word"},
    {"text": "удержим", "start": 0.2, "end": 0.7, "speaker": "Speaker_0", "type": "word"},
    {"text": "десять", "start": 0.7, "end": 1.1, "speaker": "Speaker_0", "type": "word"},
    {"text": "процентов", "start": 1.1, "end": 1.6, "speaker": "Speaker_0", "type": "word"},
    {"text": "Обсудим", "start": 2.0, "end": 2.5, "speaker": "Speaker_1", "type": "word"},
    {"text": "условие", "start": 2.5, "end": 3.0, "speaker": "Speaker_1", "type": "word"},
]


async def _mk_user(db, email: str) -> User:
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    return u


async def _mk_job(db, user: User, **kw) -> BatchJob:
    job = BatchJob(
        user_id=user.id,
        status=kw.pop("status", "done"),
        kind=kw.pop("kind", None),
        original_filename=kw.pop("original_filename", "Переговоры 08.09.m4a"),
        file_path="batch/x.m4a",
        transcription_json=kw.pop(
            "transcription_json", json.dumps({"words": WORDS, "text": "Мы удержим десять процентов"})),
        transcription_text=kw.pop("transcription_text", "Мы удержим десять процентов"),
        **kw,
    )
    db.add(job)
    await db.flush()
    return job


async def _segments(db, meeting_id: int):
    return (await db.execute(
        select(TranscriptSegmentRecord)
        .where(TranscriptSegmentRecord.session_id == meeting_id)
        .order_by(TranscriptSegmentRecord.id))).scalars().all()


# ---------- разбор распознавания ----------

def test_words_are_grouped_into_speaker_turns():
    segs = transcription_segments({"words": WORDS})
    assert [s.speaker for s in segs] == ["Speaker_0", "Speaker_1"]


def test_plain_text_without_words_becomes_one_segment():
    segs = transcription_segments({"text": "Договорились по срокам"})
    assert len(segs) == 1 and segs[0].text == "Договорились по срокам"


@pytest.mark.parametrize("empty", [{}, {"words": []}, {"text": "   "}, None])
def test_empty_transcription_gives_no_segments(empty):
    assert transcription_segments(empty) == []


# ---------- слияние в транскрипт встречи ----------

async def test_gap_fill_marks_only_first_segment(db):
    """Поведение офлайн-дозаписи (до сих пор было без тестов)."""
    user = await _mk_user(db, "gap@test.local")
    meeting = MeetingSession(user_id=user.id, created_by_user_id=user.id, is_active=True)
    db.add(meeting)
    await db.flush()

    added = await merge_transcription_into_meeting(
        db, meeting.id, {"words": WORDS},
        first_segment_prefix="[восстановлено после обрыва связи] ")
    await db.flush()

    rows = await _segments(db, meeting.id)
    assert added == 2 and len(rows) == 2
    assert rows[0].text.startswith("[восстановлено после обрыва связи] ")
    assert not rows[1].text.startswith("[восстановлено")


async def test_import_does_not_mark_segments(db):
    """Обычная запись — не дозапись, пометки об обрыве быть не должно."""
    user = await _mk_user(db, "plain@test.local")
    meeting = MeetingSession(user_id=user.id, created_by_user_id=user.id, is_active=False)
    db.add(meeting)
    await db.flush()

    await merge_transcription_into_meeting(db, meeting.id, {"words": WORDS})
    await db.flush()
    rows = await _segments(db, meeting.id)
    assert all("восстановлено" not in r.text for r in rows)
    assert all(r.origin == "batch_finalized" for r in rows)
    assert [r.speaker_label for r in rows] == ["Speaker_0", "Speaker_1"]


# ---------- запись → встреча ----------

async def test_meeting_is_created_and_transcript_moved(db):
    user = await _mk_user(db, "b2m@test.local")
    job = await _mk_job(db, user)

    meeting = await create_meeting_from_batch(db, job, user.id, title="ЖК События 6.1")
    await db.flush()

    assert meeting.title == "ЖК События 6.1"
    # запись прошлая → сразу в историю, а не в активные встречи
    assert meeting.is_active is False and meeting.status == "finalized"
    assert job.meeting_id == meeting.id
    assert len(await _segments(db, meeting.id)) == 2


async def test_customer_and_object_are_bound(db):
    """Без заказчика особенности контрагента при извлечении знаний отбрасываются."""
    user = await _mk_user(db, "b2m-cust@test.local")
    from app.models.directory import Customer
    cust = Customer(name="МРГрупп", owner_user_id=user.id)
    db.add(cust)
    await db.flush()

    job = await _mk_job(db, user)
    meeting = await create_meeting_from_batch(db, job, user.id, customer_id=cust.id)
    assert meeting.customer_id == cust.id


async def test_filename_is_used_when_title_not_given(db):
    user = await _mk_user(db, "b2m-title@test.local")
    job = await _mk_job(db, user, original_filename="ЛСР. Гарипова.m4a")
    meeting = await create_meeting_from_batch(db, job, user.id)
    assert meeting.title == "ЛСР. Гарипова.m4a"


async def test_unfinished_job_is_rejected(db):
    user = await _mk_user(db, "b2m-run@test.local")
    job = await _mk_job(db, user, status="transcribing")
    with pytest.raises(BatchToMeetingError, match="ещё не обработана"):
        await create_meeting_from_batch(db, job, user.id)


async def test_gap_fill_job_is_rejected(db):
    """Дозапись уже влита в свою встречу — второй раз её импортировать нельзя."""
    user = await _mk_user(db, "b2m-gap@test.local")
    job = await _mk_job(db, user, kind="gap_fill")
    with pytest.raises(BatchToMeetingError, match="Дозапись"):
        await create_meeting_from_batch(db, job, user.id)


async def test_second_import_is_refused(db):
    user = await _mk_user(db, "b2m-twice@test.local")
    job = await _mk_job(db, user)
    await create_meeting_from_batch(db, job, user.id)
    await db.flush()
    with pytest.raises(BatchToMeetingError, match="уже сделана встреча"):
        await create_meeting_from_batch(db, job, user.id)


async def test_job_without_transcript_is_rejected(db):
    user = await _mk_user(db, "b2m-empty@test.local")
    job = await _mk_job(db, user, transcription_json=None, transcription_text=None)
    with pytest.raises(BatchToMeetingError, match="нет транскрипта"):
        await create_meeting_from_batch(db, job, user.id)


async def test_broken_json_falls_back_to_plain_text(db):
    """Битый transcription_json не должен терять запись — есть текстовая версия."""
    user = await _mk_user(db, "b2m-broken@test.local")
    job = await _mk_job(db, user, transcription_json="{не json",
                        transcription_text="Договорились по срокам оплаты")
    meeting = await create_meeting_from_batch(db, job, user.id)
    await db.flush()
    rows = await _segments(db, meeting.id)
    assert len(rows) == 1 and "Договорились" in rows[0].text
