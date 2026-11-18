"""Job `meeting_refine`: уточнение десктоп-встречи через ElevenLabs Scribe v3, затем протокол.

Аудио встречи (mic/system) скачивается из S3, сводится в один моно-файл, распознаётся с keyterms
встречи. Реплики ElevenLabs ложатся на роли пользователя («Голос N» ↔ голос ElevenLabs по
пересечению во времени) и заменяют черновик с ПК одной транзакцией. Любой исход (готово или сбой)
заканчивается запросом финализации: при сбое протокол строится по черновику.
Ключи, ссылки и текст транскрипта в логи не пишем.
"""

import asyncio
import logging
import os
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select

from ...config import get_settings
from ...database import async_session
from ...models.file import FileRecord
from ...models.meeting import MeetingSession
from ...services import s3
from ...services.api_keys import load_api_keys
from ...services.meeting_finalize import request_finalization
from ...services.speaker_roles import get_roles_map, upsert_role
from ..batch.segment_translator import SegmentTranslator, needs_translation
from ..batch.transcription_service import BatchTranscriptionService, stt_language_settings
from ..batch.utils import group_words_by_speaker
from .audio import load_wav_energy, prepare_audio, wav_duration
from .keyterms import build_meeting_keyterms
from .mapping import Span, dominant_side, map_speakers
from .store import RefinedSegment, load_draft_segments, replace_transcript

logger = logging.getLogger("meridian.refine")

CHANNELS = ("mic", "system", "mixed")  # префиксы имён файлов приложения: «<канал>_<имя>.wav»
DEFAULT_ERROR = "Не удалось уточнить транскрипт, протокол построен по черновику"


class RefineError(Exception):
    """Ожидаемый сбой уточнения: сообщение (по-русски) уходит в refine_error."""


@dataclass
class _Source:
    user_id: int
    max_speakers: int | None
    files: dict[str, tuple[str, str]]  # канал -> (object_key, original_name)
    keyterms: list[str]


def channel_of(original_name: str) -> str | None:
    name = (original_name or "").lower()
    return next((c for c in CHANNELS if name.startswith(f"{c}_")), None)


async def _load_source(meeting_id: int) -> _Source:
    async with async_session() as db:
        meeting = await db.get(MeetingSession, meeting_id)
        if meeting is None:
            raise RefineError("Встреча не найдена")
        files = (await db.execute(
            select(FileRecord).where(
                FileRecord.meeting_id == meeting_id, FileRecord.purpose == "meeting_audio",
                FileRecord.status == "active",
            ).order_by(FileRecord.id)
        )).scalars().all()
        by_channel: dict[str, tuple[str, str]] = {}
        for f in files:  # при повторной загрузке побеждает свежий файл канала
            channel = channel_of(f.original_name)
            if channel:
                by_channel[channel] = (f.object_key, f.original_name)
        if not by_channel:
            raise RefineError("У встречи нет аудио для уточнения")
        user_id = meeting.created_by_user_id or meeting.user_id
        if user_id is None:
            raise RefineError("У встречи нет владельца")
        keyterms = await build_meeting_keyterms(db, meeting, user_id)
        return _Source(user_id, meeting.diarization_max_speakers, by_channel, keyterms)


async def _download(source: _Source, tmpdir: str) -> dict[str, str]:
    paths: dict[str, str] = {}
    for channel, (key, name) in source.files.items():
        dest = os.path.join(tmpdir, f"{channel}{os.path.splitext(name)[1].lower() or '.wav'}")
        await s3.download_to(key, dest)
        paths[channel] = dest
    return paths


def _side_energy(paths: dict[str, str]) -> tuple[np.ndarray, np.ndarray] | None:
    """Энергия обоих каналов — только когда есть и микрофон, и звук встречи (онлайн)."""
    if "mic" not in paths or "system" not in paths:
        return None
    mic, system = load_wav_energy(paths["mic"]), load_wav_energy(paths["system"])
    return (mic, system) if mic is not None and system is not None else None


def _segment_side(seg_start: float, seg_end: float, energy: tuple[np.ndarray, np.ndarray] | None) -> str | None:
    return dominant_side(energy[0], energy[1], seg_start, seg_end) if energy else None


async def _transcribe(paths: dict[str, str], source: _Source, tmpdir: str, api_key: str) -> dict:
    mix = [paths[c] for c in ("mic", "system") if c in paths] or [paths["mixed"]]
    durations = [d for d in (wav_duration(p) for p in mix) if d]
    longest = max(durations, default=0.0)
    max_hours = get_settings().desktop_refine_max_hours
    if longest > max_hours * 3600:
        raise RefineError(f"Запись длиннее {max_hours:g} ч — уточнение пропущено, протокол по черновику")
    audio = await prepare_audio(mix, tmpdir)
    if not audio:
        raise RefineError("Не удалось подготовить аудио (ffmpeg)")
    language, secondary = stt_language_settings()  # ru + tr: смешанные русско-турецкие встречи
    service = BatchTranscriptionService(
        api_key, max_speakers=source.max_speakers, keyterms=source.keyterms,
        language_code=language, secondary_language_codes=secondary)
    result = await service.transcribe(audio, timeout=max(600, min(3600, int(longest * 0.3))))
    if not result or not result.get("words"):
        raise RefineError("ElevenLabs не вернул распознавание")
    return result


_RU_CODES = {"ru", "rus"}


def _segment_language(text: str, primary: str, secondary: list[str], response_language: str | None) -> str | None:
    """Язык реплики. Batch отдаёт один language_code на файл, поэтому язык реплики — по кириллице.

    Русская по кириллице → основной язык; иноязычная → единственный дополнительный язык из
    настроек, иначе язык ответа ElevenLabs (если он не русский), иначе не определён.
    """
    if not needs_translation(text):
        return primary or None
    if len(secondary) == 1:
        return secondary[0]
    base = (response_language or "").strip().lower().split("-")[0]
    return response_language if base and base not in _RU_CODES else None


async def _translate(segments, api_key: str | None) -> dict[int, str]:
    """Русский перевод иноязычных реплик {индекс: текст}. Любой сбой — пустой ответ: уточнение не падает."""
    if not api_key or not any(needs_translation(s.text) for s in segments):
        return {}
    try:
        return await SegmentTranslator(api_key).translate([s.text for s in segments])
    except Exception as e:
        logger.warning("перевод реплик не удался (%s), оставляем оригинал", type(e).__name__)
        return {}


async def _refine(meeting_id: int, tmpdir: str) -> None:
    source = await _load_source(meeting_id)
    api_keys = await load_api_keys()
    api_key = api_keys.get("elevenlabs")
    if not api_key:
        raise RefineError("Не задан ключ ElevenLabs")
    if not get_settings().s3_enabled:
        raise RefineError("S3-хранилище не настроено")

    paths = await _download(source, tmpdir)
    transcription = await _transcribe(paths, source, tmpdir, api_key)
    segments = [s for s in group_words_by_speaker(transcription["words"]) if s.text.strip()]
    if not segments:
        raise RefineError("Распознавание не вернуло текста")
    energy = await asyncio.to_thread(_side_energy, paths)
    translations = await _translate(segments, api_keys.get("openrouter"))
    primary, secondary = stt_language_settings()
    response_language = transcription.get("language_code")

    async with async_session() as db:
        meeting = await db.get(MeetingSession, meeting_id)
        draft = await load_draft_segments(db, meeting_id)
        mapping = map_speakers(
            [Span(s.speaker, s.start, s.end) for s in segments],
            [Span(r.speaker_label or r.speaker_id, r.start_time, r.end_time) for r in draft],
        )
        sides = [_segment_side(s.start, s.end, energy) for s in segments]
        roles = await get_roles_map(db, meeting_id)
        if energy:
            await _fill_missing_roles(db, meeting_id, roles, segments, sides, mapping)
        refined = [
            RefinedSegment(
                label=mapping[s.speaker], text=s.text.strip(), start=s.start, end=s.end,
                side=side or roles.get(mapping[s.speaker]),
                language=_segment_language(s.text, primary, secondary, response_language),
                translation=translations.get(i),
                diarized_speaker=s.speaker,
            )
            for i, (s, side) in enumerate(zip(segments, sides))
        ]
        await replace_transcript(db, meeting, draft, refined)
        await db.commit()
    logger.info("meeting %s: транскрипт уточнён, реплик: %d (черновик: %d)",
                meeting_id, len(refined), len(draft))


async def _fill_missing_roles(db, meeting_id: int, roles: dict[str, str], segments, sides, mapping) -> None:
    """Метке без стороны — сторона большинства реплик по громкости каналов. Выбор пользователя не трогаем."""
    weight: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for seg, side in zip(segments, sides):
        if side:
            weight[mapping[seg.speaker]][side] += max(0.0, seg.end - seg.start)
    for label, by_side in weight.items():
        if label in roles:
            continue
        majority = max(by_side, key=by_side.get)
        await upsert_role(db, meeting_id, label, side=majority)
        roles[label] = majority


async def _mark_failed(meeting_id: int, error: str) -> None:
    async with async_session() as db:
        meeting = await db.get(MeetingSession, meeting_id)
        if meeting:
            meeting.refine_status = "failed"
            meeting.refine_error = error[:500]
            await db.commit()


async def _ensure_finalization(meeting_id: int) -> None:
    """Запросить протокол, если ещё не запрошен (повтор job-а не должен ставить его дважды)."""
    async with async_session() as db:
        meeting = await db.get(MeetingSession, meeting_id)
        if meeting is None or (meeting.finalization_status or "not_started") != "not_started":
            return
        await request_finalization(db, meeting_id)
        await db.commit()


async def handle_meeting_refine(payload: dict) -> None:
    meeting_id = payload["meeting_id"]
    async with async_session() as db:
        meeting = await db.get(MeetingSession, meeting_id)
        if meeting is None:
            logger.warning("meeting_refine: встреча %s не найдена", meeting_id)
            return
        if meeting.refine_status in ("done", "failed", "skipped"):
            already_done = True
        else:
            already_done = False
            meeting.refine_status = "running"
            meeting.refine_error = None
            await db.commit()
    if already_done:
        await _ensure_finalization(meeting_id)
        return

    tmpdir = tempfile.mkdtemp(prefix="meridian_refine_")
    error: str | None = None
    try:
        await _refine(meeting_id, tmpdir)
    except RefineError as e:
        error = str(e)
        logger.warning("meeting %s: уточнение не выполнено: %s", meeting_id, error)
    except Exception as e:
        error = DEFAULT_ERROR
        # без traceback: тексты ошибок БД несут параметры запроса, то есть реплики
        logger.error("meeting %s: сбой уточнения (%s)", meeting_id, type(e).__name__)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if error:
        await _mark_failed(meeting_id, error)
    await _ensure_finalization(meeting_id)
