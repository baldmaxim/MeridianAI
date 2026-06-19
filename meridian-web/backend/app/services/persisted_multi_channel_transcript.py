"""Сохранение/чтение нормализованных multi-channel сегментов (Этап 9.8).

ТОЛЬКО нормализованный текст + метаданные стороны/канала/времени. НИКОГДА raw/PCM/слова-с-
аудио/ответ провайдера. Дедуп по (meeting_id, segment_key). Жёсткий лимит количества строк
на встречу (DoS-guard). Функции принимают db-сессию; коммитит вызывающая сторона."""

import logging

from sqlalchemy import select, func

from ..models.transcription_cutover import MultiChannelSegmentRecord
from .authoritative_transcript import MultiSegmentView

logger = logging.getLogger("meridian.cutover")


async def count_segments(db, meeting_id: int) -> int:
    return int((await db.execute(
        select(func.count(MultiChannelSegmentRecord.id))
        .where(MultiChannelSegmentRecord.meeting_id == meeting_id)
    )).scalar() or 0)


async def segment_exists(db, meeting_id: int, segment_key: str) -> bool:
    row = (await db.execute(
        select(MultiChannelSegmentRecord.id).where(
            MultiChannelSegmentRecord.meeting_id == meeting_id,
            MultiChannelSegmentRecord.segment_key == segment_key,
        )
    )).first()
    return row is not None


async def persist_segment(
    db, *,
    meeting_id: int,
    epoch_id: int | None,
    live_session_id: str,
    seg,
    provider: str | None,
) -> bool:
    """Вставить normalized final multi-channel сегмент (если нет дубля и текст не пуст).

    Cap по количеству строк гейтит вызывающая сторона (контроллер, кэш счётчика), чтобы не
    выполнять COUNT(*) на каждый final. Возвращает True если строка добавлена, иначе False.
    """
    text = (getattr(seg, "transcript", "") or "").strip()
    if not text:
        return False
    key = getattr(seg, "segment_id", None)
    if not key:
        return False
    if await segment_exists(db, meeting_id, key):
        return False
    db.add(MultiChannelSegmentRecord(
        meeting_id=meeting_id,
        epoch_id=epoch_id,
        segment_key=str(key)[:200],
        session_id=str(live_session_id)[:40],
        channel_index=int(getattr(seg, "channel_index", 0) or 0),
        channel_label=(getattr(seg, "channel_label", None) or None),
        side=(getattr(seg, "side", None) or None),
        text=text,
        confidence=getattr(seg, "confidence", None),
        start_server_ms=int(getattr(seg, "start_server_ms", 0) or 0),
        end_server_ms=int(getattr(seg, "end_server_ms", 0) or 0),
        provider=provider,
    ))
    return True


async def load_segments(db, meeting_id: int) -> list:
    rows = (await db.execute(
        select(MultiChannelSegmentRecord)
        .where(MultiChannelSegmentRecord.meeting_id == meeting_id)
        .order_by(MultiChannelSegmentRecord.start_server_ms.asc(),
                  MultiChannelSegmentRecord.id.asc())
    )).scalars().all()
    return list(rows)


def record_to_view(rec) -> MultiSegmentView:
    return MultiSegmentView(
        segment_key=rec.segment_key, text=rec.text, side=rec.side,
        channel_label=rec.channel_label,
        start_server_ms=rec.start_server_ms, end_server_ms=rec.end_server_ms,
    )
