"""Идемпотентный обработчик батч-задачи (§15 + §16).

Аудио лежит в S3 (BatchJob.file_path = object_key). Воркер скачивает его во временную
папку, сжимает, транскрибирует, чистит temp. Возобновляемость по чекпоинту
transcription_json: если транскрипция уже есть — повторный запуск её не делает.
Терминальные ошибки → BatchJob.status='error' и нормальный возврат (без ретрая).
Неожиданные исключения пробрасываются — воркер ретраит с backoff.
"""

import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...database import async_session
from ...models.batch_job import BatchJob
from ...models.file import FileRecord
from ...models.meeting import MeetingSession, TranscriptSegmentRecord
from ...services.api_keys import load_api_keys
from ...services import s3
from .audio_compressor import AudioCompressor
from .transcription_service import BatchTranscriptionService
from .protocol_generator import ProtocolGenerator
from .utils import split_protocol_output, group_words_by_speaker, TranscriptionSegment

logger = logging.getLogger("meridian.batch")


async def _merge_gap_fill(db: AsyncSession, meeting_id: int, user_id: int | None,
                          transcription: dict) -> int:
    """Задача 5: влить сегменты офлайн-дозаписи в транскрипт встречи (без commit — коммитит вызывающий).

    Дозапись вливается ТОЛЬКО в свою встречу. Тайминги приблизительные (offset'ы внутри дыры),
    wall_clock = время слияния; первый сегмент помечается «восстановлено после обрыва связи».
    """
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        return 0
    owner = meeting.created_by_user_id or meeting.user_id
    if owner is not None and user_id is not None and owner != user_id:
        logger.warning("gap_fill: user != owner — слияние во встречу %s пропущено", meeting_id)
        return 0

    words = transcription.get("words") or []
    segments = group_words_by_speaker(words) if words else []
    if not segments and (transcription.get("text") or "").strip():
        segments = [TranscriptionSegment(speaker="Speaker_1", start=0.0, end=0.0,
                                         text=transcription["text"].strip())]
    if not segments:
        return 0

    wall = datetime.utcnow()
    added = 0
    for i, seg in enumerate(segments):
        text = (seg.text or "").strip()
        if not text:
            continue
        if i == 0:
            text = "[восстановлено после обрыва связи] " + text
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


async def handle_batch_transcribe(payload: dict) -> None:
    job_id = payload["batch_job_id"]
    api_keys = await load_api_keys()
    tmpdir: str | None = None

    try:
        async with async_session() as db:
            job = (
                await db.execute(select(BatchJob).where(BatchJob.id == job_id))
            ).scalar_one_or_none()
            if not job:
                logger.warning("batch job %s not found", job_id)
                return
            if job.status == "done":
                return  # идемпотентность

            settings = get_settings()
            # Транскрипция (с предшествующими download + compress) — только если ещё нет
            if not job.transcription_json:
                tmpdir = tempfile.mkdtemp(prefix="meridian_batch_")
                # file_path = локальный путь (fallback) ИЛИ S3-ключ (presigned)
                from_s3 = not os.path.exists(job.file_path)
                if from_s3:
                    local_audio = os.path.join(
                        tmpdir, os.path.basename(job.original_filename) or "audio"
                    )
                    await s3.download_to(job.file_path, local_audio)
                else:
                    local_audio = job.file_path
                file_to_transcribe = local_audio

                # Сжатие в opus ДО распознавания. Сжатую версию храним в S3 ВМЕСТО оригинала
                # (оригинал не нужен после первичной загрузки — экономим место). Idempotent:
                # на повторном прогоне compressed_size уже задан → не пере-сжимаем.
                ext = Path(job.original_filename).suffix.lower()
                if ext not in {".ogg", ".opus"} and not job.compressed_size:
                    compressor = AudioCompressor()
                    if compressor.is_available:
                        job.status = "compressing"
                        await db.commit()
                        res = await compressor.compress_to_opus(local_audio, tmpdir)
                        if res:
                            compressed_path, _, compressed_size = res
                            job.compressed_size = compressed_size
                            file_to_transcribe = compressed_path
                            # Заменить S3-объект на сжатый, оригинал удалить (§ хранить только сжатое)
                            if from_s3 and settings.s3_enabled:
                                old_key = job.file_path
                                new_key = s3.object_key(job.user_id, "batch_audio", "audio.ogg")
                                await s3.upload_file(compressed_path, new_key, content_type="audio/ogg")
                                rec = (
                                    await db.execute(
                                        select(FileRecord).where(FileRecord.object_key == old_key)
                                    )
                                ).scalar_one_or_none()
                                if rec:
                                    rec.object_key = new_key
                                    rec.size = compressed_size
                                    rec.mime = "audio/ogg"
                                job.file_path = new_key
                                await db.commit()
                                await s3.delete_object(old_key)
                            else:
                                await db.commit()
                    else:
                        logger.info("FFmpeg недоступен — пропуск сжатия")

                elevenlabs_key = api_keys.get("elevenlabs")
                if not elevenlabs_key:
                    job.status = "error"
                    job.error_message = "API ключ ElevenLabs не найден"
                    await db.commit()
                    return
                job.status = "transcribing"
                await db.commit()
                transcription = await BatchTranscriptionService(elevenlabs_key).transcribe(
                    file_to_transcribe
                )
                if not transcription:
                    job.status = "error"
                    job.error_message = "Ошибка транскрипции ElevenLabs"
                    await db.commit()
                    return
                job.transcription_text = transcription.get("text", "")
                job.transcription_json = json.dumps(transcription, ensure_ascii=False)
                await db.commit()
            else:
                transcription = json.loads(job.transcription_json)

            # Задача 5: офлайн-дозапись «дыры» — влить сегменты в встречу, протокол НЕ генерируем
            if job.kind == "gap_fill":
                added = 0
                if job.meeting_id:
                    added = await _merge_gap_fill(db, job.meeting_id, job.user_id, transcription)
                job.status = "done"
                await db.commit()
                logger.info("job %s: gap_fill влито %s сегментов во встречу %s",
                            job_id, added, job.meeting_id)
                return

            # Протокол (если ещё нет)
            if not job.protocol_markdown:
                openrouter_key = api_keys.get("openrouter")
                if not openrouter_key:
                    job.status = "done"
                    await db.commit()
                    logger.info("job %s: нет ключа OpenRouter, протокол пропущен", job_id)
                    return
                job.status = "generating_protocol"
                await db.commit()
                raw_protocol = await ProtocolGenerator(openrouter_key).generate(transcription)
                if raw_protocol:
                    markdown, json_data = split_protocol_output(raw_protocol)
                    job.protocol_markdown = markdown
                    if json_data:
                        job.protocol_json = json.dumps(json_data, ensure_ascii=False)

            job.status = "done"
            await db.commit()
            logger.info("job %s: выполнено", job_id)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
