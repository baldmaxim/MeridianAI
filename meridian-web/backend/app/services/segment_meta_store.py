"""Язык, перевод и метка говорящего реплики → колонки transcript_segments.

Реплика сохраняется в БД пачкой (при закрытии/опустевшей комнате), а перевод и метка
диаризации приходят позже — поэтому уже сохранённые строки досинхронизируются точечным UPDATE.
"""

import asyncio
import logging
from typing import Any, Callable, Optional

from sqlalchemy import update

from ..models.meeting import TranscriptSegmentRecord

logger = logging.getLogger("meridian.segment_meta")

MetaTuple = tuple[Optional[str], Optional[str], Optional[str]]
_EMPTY: MetaTuple = (None, None, None)
LANGUAGE_MAX = 16
DIARIZED_SPEAKER_MAX = 64


def _clean(value: Any, limit: Optional[int] = None) -> Optional[str]:
    text = str(value).strip() if value else ""
    if not text:
        return None
    return text[:limit] if limit else text


def segment_meta(seg: Any) -> MetaTuple:
    """(language, translation, diarized_speaker) сегмента; пусто → None, длина — по колонкам."""
    return (
        _clean(getattr(seg, "language", None), LANGUAGE_MAX),
        _clean(getattr(seg, "translation", None)),
        _clean(getattr(seg, "diarized_speaker", None), DIARIZED_SPEAKER_MAX),
    )


class SegmentMetaSync:
    """Следит за тем, что из language/translation/diarized_speaker уже лежит в БД."""

    def __init__(self, meeting_id: int) -> None:
        self._meeting_id = meeting_id
        self._written: dict[str, MetaTuple] = {}  # segment_id → что записано в строке БД
        self._lock = asyncio.Lock()

    def mark_inserted(self, seg: Any) -> None:
        """Строка только что вставлена с текущими полями сегмента."""
        self._written[seg.segment_id] = segment_meta(seg)

    def mark_existing(self, segment_ids: set[str]) -> None:
        """Строки уже были в БД — что в них лежит, неизвестно (считаем пустыми)."""
        for segment_id in segment_ids:
            self._written.setdefault(segment_id, _EMPTY)

    async def flush(self, session_factory: Callable, segments: list) -> None:
        """UPDATE сохранённых строк, у которых поля сегмента изменились. Ошибки — только в лог."""
        async with self._lock:
            changed = []
            for seg in list(segments):
                known = self._written.get(seg.segment_id)
                meta = segment_meta(seg)
                if known is not None and meta != known and meta != _EMPTY:
                    changed.append((seg.segment_id, meta))
            if not changed:
                return
            try:
                async with session_factory() as db:
                    for segment_id, meta in changed:
                        # None не затирает уже записанное (строки десктопа/реплея, поздний порядок событий)
                        values = {
                            name: value
                            for name, value in zip(("language", "translation", "diarized_speaker"), meta)
                            if value is not None
                        }
                        await db.execute(
                            update(TranscriptSegmentRecord)
                            .where(TranscriptSegmentRecord.session_id == self._meeting_id,
                                   TranscriptSegmentRecord.segment_id == segment_id)
                            .values(**values)
                        )
                    await db.commit()
                for segment_id, meta in changed:
                    self._written[segment_id] = meta
            except Exception as e:
                logger.warning("[room %s] обновление языка/перевода реплик не записано: %s",
                               self._meeting_id, type(e).__name__)
