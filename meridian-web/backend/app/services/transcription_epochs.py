"""Эпохи транскрипции (Этап 9.8): переключения авторитетного источника на server timeline.

Чистые помощники (инварианты/текущий источник) + DB CRUD. Функции принимают db-сессию и
делают flush (id), коммитит вызывающая сторона. Инвариант: ровно одна открытая эпоха;
границы монотонны; эпоха 0 при первом promote моделирует прошлый single-отрезок.
"""

from sqlalchemy import select

from ..models.transcription_cutover import TranscriptionEpoch
from .authoritative_transcript import EpochView, SOURCE_SINGLE, SOURCE_MULTI


# ----------------------------- pure helpers -----------------------------

def current_source_from_epochs(epochs: list) -> str:
    """Источник последней (по индексу) эпохи; пусто → single (поведение по умолчанию)."""
    if not epochs:
        return SOURCE_SINGLE
    last = max(epochs, key=lambda e: e.epoch_index)
    return last.source


def open_epoch(epochs: list):
    """Открытая эпоха (end is None) с наибольшим индексом, либо None."""
    opens = [e for e in epochs if e.end_server_ms is None]
    if not opens:
        return None
    return max(opens, key=lambda e: e.epoch_index)


def epoch_records_to_views(epochs: list) -> list:
    return [
        EpochView(epoch_index=e.epoch_index, source=e.source,
                  start_server_ms=e.start_server_ms, end_server_ms=e.end_server_ms)
        for e in epochs
    ]


# ----------------------------- DB CRUD -----------------------------

async def load_epochs(db, meeting_id: int) -> list:
    rows = (await db.execute(
        select(TranscriptionEpoch)
        .where(TranscriptionEpoch.meeting_id == meeting_id)
        .order_by(TranscriptionEpoch.epoch_index.asc())
    )).scalars().all()
    return list(rows)


async def switch_to(
    db, meeting_id: int, *,
    to_source: str,
    at_server_ms: int,
    reason: str,
    by_user_id: int | None = None,
    live_session_id: str | None = None,
    automatic: bool = False,
) -> TranscriptionEpoch:
    """Закрыть открытую эпоху на at_server_ms и открыть новую source=to_source.

    Если эпох ещё нет и переходим на multi — создаём baseline single эпоху 0
    [0, at_server_ms) reason="initial", затем multi эпоху 1. at_server_ms клампится
    так, чтобы не уйти левее старта предыдущей эпохи (монотонность границ).
    """
    epochs = await load_epochs(db, meeting_id)

    if not epochs:
        if to_source == SOURCE_MULTI:
            at = max(0, int(at_server_ms))
            db.add(TranscriptionEpoch(
                meeting_id=meeting_id, epoch_index=0, source=SOURCE_SINGLE,
                start_server_ms=0, end_server_ms=at, reason="initial", automatic=False,
            ))
            new = TranscriptionEpoch(
                meeting_id=meeting_id, epoch_index=1, source=SOURCE_MULTI,
                start_server_ms=at, end_server_ms=None, reason=reason,
                automatic=automatic, created_by_user_id=by_user_id,
                live_session_id=live_session_id,
            )
            db.add(new)
            await db.flush()
            return new
        # переход на single без эпох — уже single по умолчанию, создаём открытую эпоху 0
        new = TranscriptionEpoch(
            meeting_id=meeting_id, epoch_index=0, source=SOURCE_SINGLE,
            start_server_ms=max(0, int(at_server_ms)), end_server_ms=None, reason=reason,
            automatic=automatic, created_by_user_id=by_user_id,
        )
        db.add(new)
        await db.flush()
        return new

    last = max(epochs, key=lambda e: e.epoch_index)
    at = max(int(at_server_ms), int(last.start_server_ms))  # монотонная граница
    cur_open = open_epoch(epochs)
    if cur_open is not None:
        cur_open.end_server_ms = at
    new = TranscriptionEpoch(
        meeting_id=meeting_id, epoch_index=last.epoch_index + 1, source=to_source,
        start_server_ms=at, end_server_ms=None, reason=reason,
        automatic=automatic, created_by_user_id=by_user_id, live_session_id=live_session_id,
    )
    db.add(new)
    await db.flush()
    return new


async def close_open_epoch(db, meeting_id: int, at_server_ms: int) -> None:
    """Закрыть текущую открытую эпоху (например, при финализации встречи)."""
    epochs = await load_epochs(db, meeting_id)
    cur = open_epoch(epochs)
    if cur is not None and cur.end_server_ms is None:
        cur.end_server_ms = max(int(at_server_ms), int(cur.start_server_ms))
