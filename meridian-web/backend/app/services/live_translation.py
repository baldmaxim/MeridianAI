"""Перевод иноязычных реплик живой встречи на русский (асинхронно, мимо пайплайна)."""

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from ..core.batch.segment_translator import SegmentTranslator, needs_translation
from ..core.transcription.models import CommittedSegment

logger = logging.getLogger("meridian.live_translation")

_RU_CODES = {"ru", "rus"}
# Параллельных переводов не больше: каждый — блокирующий HTTP-вызов в потоке
MAX_PARALLEL = 2


def segment_needs_translation(segment: CommittedSegment) -> bool:
    """Язык известен и не русский → да; неизвестен → по эвристике кириллицы."""
    language = (segment.language or "").strip().lower().split("-")[0]
    if language:
        return language not in _RU_CODES
    return needs_translation(segment.text)


class LiveSegmentTranslator:
    """Переводит реплики и отдаёт результат через send({"type": "segment_translation", ...})."""

    def __init__(self, get_api_key: Callable[[], Optional[str]],
                 send: Callable[[dict], Awaitable[None]],
                 on_translated: Optional[Callable[[CommittedSegment], None]] = None) -> None:
        self._get_api_key = get_api_key
        self._send = send
        self._on_translated = on_translated
        self._sem = asyncio.Semaphore(MAX_PARALLEL)
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, segment: CommittedSegment) -> None:
        """Поставить перевод в фон. Нет ключа или реплика русская — молча пропустить."""
        api_key = self._get_api_key()
        if not api_key or not (segment.text or "").strip() or not segment_needs_translation(segment):
            return
        task = asyncio.create_task(self._translate(segment, api_key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _translate(self, segment: CommittedSegment, api_key: str) -> None:
        try:
            async with self._sem:
                # translate() сам отсеивает русские реплики (needs_translation)
                result = await SegmentTranslator(api_key).translate([segment.text])
            text = result.get(0)
            if text:
                segment.translation = text
                await self._send({
                    "type": "segment_translation",
                    "segment_id": segment.segment_id,
                    "text": text,
                })
                if self._on_translated:
                    self._on_translated(segment)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("перевод реплики не получен: %s", type(e).__name__)

    def cancel_all(self) -> None:
        for task in list(self._tasks):
            task.cancel()
