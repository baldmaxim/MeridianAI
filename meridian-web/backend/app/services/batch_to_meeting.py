# -*- coding: utf-8 -*-
"""Диктофонная запись → встреча со структурным протоколом.

Батч распознаёт аудио и делает markdown-протокол внутри самой задачи, но решения,
поручения, риски и открытые вопросы наполняет ТОЛЬКО финализация встречи
(`meeting_finalize`), а извлечение знаний работает по встрече. Поэтому загруженная запись
упиралась в тупик: текст есть, структурного протокола и кандидатов в базу знаний нет —
на проде за всё время 0 решений, 0 поручений, 0 рисков, 0 открытых вопросов.

Здесь готовый батч превращается во встречу: сегменты переносятся в транскрипт встречи,
ставится финализация (она же дальше поставит извлечение знаний). Привязка к заказчику и
объекту важна не для красоты: без customer_id особенности контрагента при извлечении
знаний отбрасываются.
"""

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.batch.utils import (
    TranscriptionSegment, group_words_by_speaker, parse_translation_map,
)
from ..models.batch_job import BatchJob
from ..models.directory import MeetingParticipant
from ..models.meeting import MeetingSession, TranscriptSegmentRecord

logger = logging.getLogger("meridian.batch2meeting")


class BatchToMeetingError(ValueError):
    """Батч нельзя превратить во встречу (сообщение уходит пользователю)."""


def transcription_segments(transcription: dict) -> list[TranscriptionSegment]:
    """Реплики из результата распознавания: по словам, иначе одним куском."""
    words = (transcription or {}).get("words") or []
    segments = group_words_by_speaker(words) if words else []
    if not segments and ((transcription or {}).get("text") or "").strip():
        segments = [TranscriptionSegment(speaker="Speaker_1", start=0.0, end=0.0,
                                         text=transcription["text"].strip())]
    return segments


async def merge_transcription_into_meeting(
    db: AsyncSession, meeting_id: int, transcription: dict,
    *, first_segment_prefix: str | None = None,
    translations: dict[int, str] | None = None,
) -> int:
    """Влить реплики распознавания в транскрипт встречи. Коммитит вызывающий.

    first_segment_prefix — пометка на первой реплике (дозапись помечает обрыв связи).
    translations — русский перевод иноязычных реплик по индексу. Во встречу переносим
    перевод: финализация и извлечение знаний работают по-русски, иначе турецкие реплики
    осядут в базе знаний как есть и не найдутся поиском. Оригинал остаётся в батче.
    """
    segments = transcription_segments(transcription)
    if not segments:
        return 0
    wall = datetime.utcnow()
    added = 0
    for i, seg in enumerate(segments):
        text = ((translations or {}).get(i) or seg.text or "").strip()
        if not text:
            continue
        if i == 0 and first_segment_prefix:
            text = first_segment_prefix + text
        db.add(TranscriptSegmentRecord(
            session_id=meeting_id,
            segment_id=uuid.uuid4().hex[:12],
            text=text,
            start_time=float(seg.start or 0),
            end_time=float(seg.end or 0),
            wall_clock=wall,
            speaker_id=(seg.speaker or "unknown_speaker")[:50],
            speaker_label=(seg.speaker or None),
            origin="batch_finalized",
            word_count=len(text.split()),
        ))
        added += 1
    return added


def _load_transcription(job: BatchJob) -> dict:
    if job.transcription_json:
        try:
            data = json.loads(job.transcription_json)
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            logger.warning("job %s: transcription_json не разобран", job.id)
    text = (job.transcription_text or "").strip()
    if text:
        return {"text": text}
    return {}


async def create_meeting_from_batch(
    db: AsyncSession, job: BatchJob, user_id: int,
    *, customer_id: int | None = None, object_id: int | None = None,
    title: str | None = None, ai_settings_profile_id: int | None = None,
) -> MeetingSession:
    """Создать встречу из готового батча и перенести в неё транскрипт. Коммитит вызывающий."""
    if job.status != "done":
        raise BatchToMeetingError("Запись ещё не обработана")
    if job.kind == "gap_fill":
        raise BatchToMeetingError("Дозапись уже влита в свою встречу")
    if job.meeting_id:
        raise BatchToMeetingError("Из этой записи уже сделана встреча")

    transcription = _load_transcription(job)
    if not transcription:
        raise BatchToMeetingError("У записи нет транскрипта")

    meeting = MeetingSession(
        user_id=user_id,
        created_by_user_id=user_id,
        # Запись прошлая, а не идущая сейчас: сразу в историю, не в активные.
        is_active=False,
        status="finalized",
        customer_id=customer_id,
        object_id=object_id,
        title=(title or job.original_filename or "Встреча из записи")[:90],
        ai_settings_profile_id=ai_settings_profile_id,
    )
    db.add(meeting)
    await db.flush()

    db.add(MeetingParticipant(meeting_id=meeting.id, user_id=user_id, role="owner"))
    added = await merge_transcription_into_meeting(
        db, meeting.id, transcription,
        translations=parse_translation_map(job.transcription_translation_json),
    )
    if not added:
        raise BatchToMeetingError("Не удалось перенести реплики записи")

    job.meeting_id = meeting.id
    await db.flush()
    logger.info("батч %s → встреча %s, реплик перенесено: %s", job.id, meeting.id, added)
    return meeting
