"""Запись уточнённого транскрипта: черновик с ПК уходит в JSON, на его место встают реплики ElevenLabs."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.meeting import MeetingSession, TranscriptSegmentRecord

DRAFT_ORIGIN = "desktop"
# Черновик — всё, что было до уточнения: фразы ПК (офлайн) и сегменты живого распознавания сервера
# (онлайн-режим: звук шёл в WS, origin = SegmentOrigin.LIVE_COMMITTED). Иначе уточнённые реплики
# легли бы поверх живых дублями.
DRAFT_ORIGINS = (DRAFT_ORIGIN, "live_committed")
REFINED_ORIGIN = "refined"
# speaker_id по стороне (как у каналов приложения); сторона неизвестна — нейтральный.
SPEAKER_ID_BY_SIDE = {"self": "desktop_mic", "opponent": "desktop_system"}
NEUTRAL_SPEAKER_ID = "desktop_mixed"


@dataclass
class RefinedSegment:
    label: str
    text: str
    start: float
    end: float
    side: str | None  # self | opponent | None
    language: str | None = None  # ISO-код реплики (ru, tr…); None — не определён
    translation: str | None = None  # русский перевод иноязычной реплики
    diarized_speaker: str | None = None  # голос ElevenLabs («Speaker_0»), как у живых сегментов


def refined_segment_id(meeting_id: int, index: int) -> str:
    """segment_id (String(12), UNIQUE): детерминированный — повторная запись даёт те же id."""
    return hashlib.sha256(f"refine:{meeting_id}:{index}".encode("utf-8")).hexdigest()[:12]


async def load_draft_segments(db: AsyncSession, meeting_id: int) -> list[TranscriptSegmentRecord]:
    return list((await db.execute(
        select(TranscriptSegmentRecord)
        .where(TranscriptSegmentRecord.session_id == meeting_id,
               TranscriptSegmentRecord.origin.in_(DRAFT_ORIGINS))
        .order_by(TranscriptSegmentRecord.start_time, TranscriptSegmentRecord.id)
    )).scalars().all())


def serialize_draft(rows: list[TranscriptSegmentRecord]) -> str:
    return json.dumps([
        {
            "segment_id": r.segment_id, "speaker_id": r.speaker_id, "speaker_label": r.speaker_label,
            "text": r.text, "start_time": r.start_time, "end_time": r.end_time,
            "wall_clock": r.wall_clock.isoformat() if r.wall_clock else None,
            "origin": r.origin, "word_count": r.word_count,
            "language": r.language, "translation": r.translation, "diarized_speaker": r.diarized_speaker,
        }
        for r in rows
    ], ensure_ascii=False)


async def replace_transcript(
    db: AsyncSession, meeting: MeetingSession, draft: list[TranscriptSegmentRecord],
    refined: list[RefinedSegment],
) -> None:
    """Черновик → meeting.transcript_draft_json, уточнённые реплики вместо него. Коммитит вызывающий.

    Поправки сегментов (meeting_speaker_segment_corrections) без FK и ключуются по segment_id:
    не трогаем — при откате из черновика они снова совпадут с сегментами.
    """
    meeting.transcript_draft_json = serialize_draft(draft)
    await db.execute(delete(TranscriptSegmentRecord).where(
        TranscriptSegmentRecord.session_id == meeting.id,
        TranscriptSegmentRecord.origin.in_(DRAFT_ORIGINS),
    ))
    for i, seg in enumerate(refined):
        db.add(TranscriptSegmentRecord(
            session_id=meeting.id,
            segment_id=refined_segment_id(meeting.id, i),
            text=seg.text,
            start_time=seg.start,
            end_time=seg.end,
            wall_clock=meeting.started_at + timedelta(seconds=seg.start),
            speaker_id=SPEAKER_ID_BY_SIDE.get(seg.side or "", NEUTRAL_SPEAKER_ID),
            speaker_label=seg.label,
            language=seg.language,
            translation=seg.translation,
            diarized_speaker=seg.diarized_speaker,
            origin=REFINED_ORIGIN,
            word_count=len(seg.text.split()),
        ))
    meeting.refine_status = "done"
    meeting.refine_error = None
    meeting.refined_at = datetime.utcnow()
    await db.flush()
