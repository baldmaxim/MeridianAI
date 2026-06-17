"""Сервис segment-level коррекций диаризации (Этап 8).

Overlay поверх raw STT. Пустые коррекции (нет corrected_label, side, note) не хранятся.
Resolver применяет правило приоритета: segment-side → corrected_label→role → original_label→role → None.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.speaker_correction import MeetingSpeakerSegmentCorrection
from ..schemas.speaker_correction import SpeakerSegmentCorrectionOut
from .speaker_roles import to_public_side

logger = logging.getLogger("meridian.speaker_corrections")


def normalize_segment_key(value: str) -> str:
    """Обрезать и валидировать segment_key. Пустой → ValueError (API → 422)."""
    key = (value or "").strip()
    if not key:
        raise ValueError("segment_key обязателен")
    return key[:200]


def normalize_speaker_label(value: str | None) -> str | None:
    """Обрезать label; пустая строка → None."""
    if value is None:
        return None
    label = str(value).strip()
    return label[:120] if label else None


async def list_segment_corrections(
    db: AsyncSession, meeting_id: int,
) -> dict[str, MeetingSpeakerSegmentCorrection]:
    """{segment_key: correction} — для resolver/rebuild."""
    rows = (await db.execute(
        select(MeetingSpeakerSegmentCorrection)
        .where(MeetingSpeakerSegmentCorrection.meeting_id == meeting_id)
    )).scalars().all()
    return {r.segment_key: r for r in rows}


async def get_segment_corrections_cache(db: AsyncSession, meeting_id: int) -> dict[str, dict]:
    """{segment_key: {"side", "corrected_speaker_label"}} — лёгкий кэш для live SessionManager."""
    rows = await list_segment_corrections(db, meeting_id)
    return {
        key: {"side": r.side, "corrected_speaker_label": r.corrected_speaker_label}
        for key, r in rows.items()
    }


async def get_segment_corrections_out(
    db: AsyncSession, meeting_id: int,
) -> list[SpeakerSegmentCorrectionOut]:
    rows = (await db.execute(
        select(MeetingSpeakerSegmentCorrection)
        .where(MeetingSpeakerSegmentCorrection.meeting_id == meeting_id)
        .order_by(MeetingSpeakerSegmentCorrection.segment_key.asc())
    )).scalars().all()
    return [SpeakerSegmentCorrectionOut.model_validate(r) for r in rows]


async def upsert_segment_correction(
    db: AsyncSession, meeting_id: int, segment_key: str, *,
    original_speaker_label: str | None = None,
    corrected_speaker_label: str | None = None,
    side: str | None = None,
    note: str | None = None,
    user_id: int | None = None,
) -> MeetingSpeakerSegmentCorrection | None:
    """Создать/обновить коррекцию. Пустая (нет corrected_label/side/note) → удалить. Коммитит вызывающий."""
    key = normalize_segment_key(segment_key)
    original = normalize_speaker_label(original_speaker_label)
    corrected = normalize_speaker_label(corrected_speaker_label)
    norm_side = to_public_side(side)
    norm_note = (note or "").strip() or None

    existing = (await db.execute(
        select(MeetingSpeakerSegmentCorrection).where(
            MeetingSpeakerSegmentCorrection.meeting_id == meeting_id,
            MeetingSpeakerSegmentCorrection.segment_key == key,
        )
    )).scalar_one_or_none()

    # пустая коррекция — не храним
    if corrected is None and norm_side is None and norm_note is None:
        if existing:
            await db.delete(existing)
            await db.flush()
        return None

    if existing:
        existing.original_speaker_label = original if original is not None else existing.original_speaker_label
        existing.corrected_speaker_label = corrected
        existing.side = norm_side
        existing.note = norm_note
        existing.updated_by_user_id = user_id
        await db.flush()
        await db.refresh(existing)
        return existing

    row = MeetingSpeakerSegmentCorrection(
        meeting_id=meeting_id, segment_key=key,
        original_speaker_label=original, corrected_speaker_label=corrected,
        side=norm_side, note=norm_note,
        created_by_user_id=user_id, updated_by_user_id=user_id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def delete_segment_correction(db: AsyncSession, meeting_id: int, segment_key: str) -> bool:
    key = normalize_segment_key(segment_key)
    existing = (await db.execute(
        select(MeetingSpeakerSegmentCorrection).where(
            MeetingSpeakerSegmentCorrection.meeting_id == meeting_id,
            MeetingSpeakerSegmentCorrection.segment_key == key,
        )
    )).scalar_one_or_none()
    if existing is None:
        return False
    await db.delete(existing)
    await db.flush()
    return True


async def bulk_upsert_segment_corrections(
    db: AsyncSession, meeting_id: int, items: list, user_id: int | None = None,
) -> list[SpeakerSegmentCorrectionOut]:
    """items: список с .segment_key + полями PUT. Коммитит вызывающий."""
    for it in items:
        await upsert_segment_correction(
            db, meeting_id, it.segment_key,
            original_speaker_label=it.original_speaker_label,
            corrected_speaker_label=it.corrected_speaker_label,
            side=it.side, note=it.note, user_id=user_id,
        )
    return await get_segment_corrections_out(db, meeting_id)


# ── Resolver (pure) ───────────────────────────────────────────────────────────

@dataclass
class ResolvedSpeakerForSegment:
    original_speaker_label: str | None
    corrected_speaker_label: str | None
    effective_speaker_label: str | None
    side: str | None
    corrected: bool


def resolve_speaker_for_segment(
    segment_key: str,
    original_speaker_label: str | None,
    corrections: dict[str, MeetingSpeakerSegmentCorrection],
    roles_map: dict[str, str],
) -> ResolvedSpeakerForSegment:
    """Определить эффективного спикера/сторону реплики по правилу приоритета:

      1) segment-level side correction;
      2) corrected_speaker_label → speaker role map;
      3) original_speaker_label → speaker role map;
      4) None.
    """
    corr = corrections.get(segment_key)
    corrected_label = corr.corrected_speaker_label if corr else None
    effective = corrected_label or original_speaker_label

    side: str | None = None
    if corr and corr.side:
        side = to_public_side(corr.side)
    if side is None and corrected_label:
        side = to_public_side(roles_map.get(corrected_label))
    if side is None and original_speaker_label:
        side = to_public_side(roles_map.get(original_speaker_label))

    corrected = bool(corr and (corr.side or corr.corrected_speaker_label))
    return ResolvedSpeakerForSegment(
        original_speaker_label=original_speaker_label,
        corrected_speaker_label=corrected_label,
        effective_speaker_label=effective,
        side=side,
        corrected=corrected,
    )
