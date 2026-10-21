# -*- coding: utf-8 -*-
"""Приём встречи от десктоп-приложения: идемпотентные записи.

Приложение повторяет любой запрос после обрыва сети, поэтому каждая запись здесь — upsert:
встреча ищется по (user_id, client_uuid), сегмент — по серверному segment_id, выведенному из
идентификаторов приложения, заметки заменяются целиком. Повтор не плодит дубли.

Все функции коммит оставляют вызывающему.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.desktop import DesktopMeetingLink
from ..models.directory import MeetingParticipant
from ..models.meeting import MeetingSession, TranscriptSegmentRecord
from .meeting_finalize import close_and_request_finalization
from .speaker_roles import upsert_role

logger = logging.getLogger("meridian.desktop_sync")

# Стороны по каналам. Метки совпадают с тем, как стороны подписаны в самой встрече.
LABEL_SELF = "Мы"
LABEL_OPPONENT = "Оппонент"
CHANNEL_SPEAKERS = {
    "mic": ("desktop_mic", LABEL_SELF),
    "system": ("desktop_system", LABEL_OPPONENT),
}
MIXED_SPEAKER_ID = "desktop_mixed"
MIXED_DEFAULT_LABEL = "Speaker_1"

DEFAULT_TITLE = "Встреча с компьютера"


class DesktopMeetingClosedError(ValueError):
    """Встреча уже финализирована — сегменты в неё не принимаются."""


def to_naive_utc(value: datetime | None) -> datetime | None:
    """В БД даты хранятся как naive UTC: aware приводим к UTC, naive считаем уже UTC."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def segment_server_id(client_uuid: str, client_segment_id: str) -> str:
    """Серверный segment_id (String(12), UNIQUE глобально): стабильно выводится из id приложения."""
    return hashlib.sha256(f"{client_uuid}:{client_segment_id}".encode("utf-8")).hexdigest()[:12]


def is_finalized(meeting: MeetingSession) -> bool:
    return meeting.status == "finalized" or (meeting.finalization_status or "not_started") != "not_started"


# ── встречи ───────────────────────────────────────────────────────────────


async def get_link(db: AsyncSession, user_id: int, client_uuid: str) -> DesktopMeetingLink | None:
    return (await db.execute(
        select(DesktopMeetingLink).where(
            DesktopMeetingLink.user_id == user_id, DesktopMeetingLink.client_uuid == client_uuid
        )
    )).scalar_one_or_none()


async def get_linked_meeting(
    db: AsyncSession, user_id: int, meeting_id: int,
) -> tuple[MeetingSession, DesktopMeetingLink] | None:
    """Встреча, принятая от приложения этим пользователем; чужая и несуществующая неотличимы."""
    row = (await db.execute(
        select(MeetingSession, DesktopMeetingLink)
        .join(DesktopMeetingLink, DesktopMeetingLink.meeting_id == MeetingSession.id)
        .where(MeetingSession.id == meeting_id, DesktopMeetingLink.user_id == user_id)
    )).first()
    return (row[0], row[1]) if row else None


async def _create_meeting(
    db: AsyncSession, user_id: int, device_id: int, client_uuid: str, *, title: str,
    started_at: datetime, ended_at: datetime | None, capture_mode: str,
    customer_id: int | None, object_id: int | None,
) -> DesktopMeetingLink:
    meeting = MeetingSession(
        user_id=user_id,
        created_by_user_id=user_id,
        # Запись уже прошла на компьютере: сразу в историю, а не в идущие сейчас.
        is_active=False,
        status="active",
        customer_id=customer_id,
        object_id=object_id,
        title=title,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(meeting)
    await db.flush()
    db.add(MeetingParticipant(meeting_id=meeting.id, user_id=user_id, role="owner"))
    link = DesktopMeetingLink(
        user_id=user_id, device_id=device_id, client_uuid=client_uuid,
        meeting_id=meeting.id, capture_mode=capture_mode,
    )
    db.add(link)
    await db.flush()
    if capture_mode == "online":
        # Онлайн-встреча: микрофон — «мы», звук системы — «оппонент». Роли заводим сразу,
        # чтобы дерево общения и протокол знали стороны без ручной разметки.
        await upsert_role(db, meeting.id, LABEL_SELF, side="self", assigned_by_user_id=user_id)
        await upsert_role(db, meeting.id, LABEL_OPPONENT, side="opponent", assigned_by_user_id=user_id)
    return link


async def upsert_meeting(
    db: AsyncSession, user_id: int, device_id: int, client_uuid: str, *, title: str | None,
    started_at: datetime, ended_at: datetime | None, capture_mode: str,
    customer_id: int | None, object_id: int | None,
    negotiation_type: str | None = None, key_terms: str | None = None,
    opponent_weaknesses: str | None = None,
) -> tuple[MeetingSession, bool]:
    """(встреча, created). Повтор с тем же client_uuid обновляет название, конец встречи и переданный контекст."""
    clean_title = ((title or "").strip() or DEFAULT_TITLE)[:255]
    started = to_naive_utc(started_at)
    ended = to_naive_utc(ended_at)

    link = await get_link(db, user_id, client_uuid)
    created = False
    if link is None:
        try:
            # SAVEPOINT: два одновременных запроса с одним client_uuid — проигравший
            # упрётся в UNIQUE и подхватит встречу победителя, а не получит 500.
            async with db.begin_nested():
                link = await _create_meeting(
                    db, user_id, device_id, client_uuid, title=clean_title,
                    started_at=started, ended_at=ended, capture_mode=capture_mode,
                    customer_id=customer_id, object_id=object_id,
                )
            created = True
        except IntegrityError:
            link = await get_link(db, user_id, client_uuid)
            if link is None:
                raise
    meeting = await db.get(MeetingSession, link.meeting_id)
    if not created:
        meeting.title = clean_title
        if ended is not None:
            meeting.ended_at = ended
    apply_context(meeting, negotiation_type=negotiation_type, key_terms=key_terms,
                  opponent_weaknesses=opponent_weaknesses)
    return meeting, created


def apply_context(
    meeting: MeetingSession, *, negotiation_type: str | None = None,
    key_terms: str | None = None, opponent_weaknesses: str | None = None,
) -> bool:
    """Контекст встречи как на сайте. None — не менять; пустая строка — очистить (NULL).

    key_terms пишется в meeting_notes («Ключевые условия / цели»). True — что-то передано.
    """
    changed = False
    for attr, value in (
        ("negotiation_type", negotiation_type),
        ("meeting_notes", key_terms),
        ("opponent_weaknesses", opponent_weaknesses),
    ):
        if value is None:
            continue
        setattr(meeting, attr, value.strip() or None)
        changed = True
    return changed


async def list_meetings(db: AsyncSession, user_id: int, limit: int = 200) -> list[tuple[MeetingSession, DesktopMeetingLink]]:
    rows = (await db.execute(
        select(MeetingSession, DesktopMeetingLink)
        .join(DesktopMeetingLink, DesktopMeetingLink.meeting_id == MeetingSession.id)
        .where(DesktopMeetingLink.user_id == user_id)
        .order_by(MeetingSession.started_at.desc(), MeetingSession.id.desc())
        .limit(limit)
    )).all()
    return [(m, l) for m, l in rows]


# ── сегменты ──────────────────────────────────────────────────────────────


@dataclass
class SegmentIn:
    client_segment_id: str
    text: str
    start_time: float
    end_time: float
    wall_clock: datetime | None
    channel: str
    speaker_label: str | None


def _speaker_for(seg: SegmentIn) -> tuple[str, str]:
    if seg.channel in CHANNEL_SPEAKERS:
        return CHANNEL_SPEAKERS[seg.channel]
    return MIXED_SPEAKER_ID, ((seg.speaker_label or "").strip()[:100] or MIXED_DEFAULT_LABEL)


async def upsert_segments(
    db: AsyncSession, meeting: MeetingSession, link: DesktopMeetingLink, segments: list[SegmentIn],
) -> tuple[int, int]:
    """(создано, обновлено). Повтор обновляет текст и время, дублей не даёт."""
    if is_finalized(meeting):
        raise DesktopMeetingClosedError("Встреча уже финализирована")

    # Повтор одного id внутри запроса — побеждает последний.
    by_id: dict[str, SegmentIn] = {}
    for seg in segments:
        if (seg.text or "").strip():
            by_id[segment_server_id(link.client_uuid, seg.client_segment_id)] = seg
    if not by_id:
        return 0, 0

    existing = {
        r.segment_id: r for r in (await db.execute(
            select(TranscriptSegmentRecord).where(TranscriptSegmentRecord.segment_id.in_(list(by_id)))
        )).scalars().all()
    }
    created = updated = 0
    for server_id, seg in by_id.items():
        text = seg.text.strip()
        speaker_id, label = _speaker_for(seg)
        wall = to_naive_utc(seg.wall_clock) or (meeting.started_at + timedelta(seconds=seg.start_time))
        row = existing.get(server_id)
        if row is not None:
            if row.session_id != meeting.id:
                # 48 бит хэша: чужой сегмент с тем же id — практически невозможен, но портить его нельзя.
                logger.warning("segment_id %s принадлежит другой встрече — пропущен", server_id)
                continue
            row.text = text
            row.start_time = seg.start_time
            row.end_time = seg.end_time
            row.wall_clock = wall
            row.speaker_id = speaker_id
            row.speaker_label = label
            row.word_count = len(text.split())
            updated += 1
        else:
            db.add(TranscriptSegmentRecord(
                session_id=meeting.id,
                segment_id=server_id,
                text=text,
                start_time=seg.start_time,
                end_time=seg.end_time,
                wall_clock=wall,
                speaker_id=speaker_id,
                speaker_label=label,
                origin="desktop",
                word_count=len(text.split()),
            ))
            created += 1
    await db.flush()
    return created, updated


# ── заметки ───────────────────────────────────────────────────────────────


def format_notes(notes: list[tuple[float, str]]) -> str | None:
    """Строки `[мм:сс] текст` по времени. Перевод строки в заметке схлопывается: одна заметка — одна строка."""
    lines: list[tuple[float, str]] = []
    for at, text in notes:
        clean = " ".join((text or "").split())
        if not clean:
            continue
        total = max(0, int(at))
        lines.append((at, f"[{total // 60:02d}:{total % 60:02d}] {clean}"))
    lines.sort(key=lambda x: x[0])  # sort устойчив: заметки с одной секундой остаются в порядке прихода
    return "\n".join(line for _, line in lines) or None


# ── финализация ───────────────────────────────────────────────────────────


async def finalize(db: AsyncSession, meeting: MeetingSession) -> None:
    """Завершить встречу и поставить протокол в очередь. Повтор на финализированной ничего не меняет."""
    if is_finalized(meeting):
        return
    if not meeting.ended_at:
        meeting.ended_at = datetime.utcnow()
    # Встреча от приложения создаётся неактивной, поэтому статус закрываем здесь:
    # общий сервис закрывает только live-встречи.
    meeting.status = "finalized"
    await close_and_request_finalization(db, meeting)
    await db.flush()


async def reset_stale_live_flags(db: AsyncSession) -> int:
    """Снять is_active с встреч приложения после рестарта процесса.

    Флаг ставит живой WS приложения и снимает при отключении последнего сокета.
    Упавший процесс снять его не успевает, а после рестарта сокетов нет — иначе
    встреча навсегда остаётся «идущей» и пропадает из истории.
    """
    result = await db.execute(
        update(MeetingSession)
        .where(
            MeetingSession.is_active.is_(True),
            MeetingSession.id.in_(select(DesktopMeetingLink.meeting_id)),
        )
        .values(is_active=False)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return result.rowcount or 0
