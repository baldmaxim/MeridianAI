"""Задача 3: job-обработчик архива живого аудио встречи.

Вход: WAV-файл на диске (создан MeetingRoom при финализации). Шаги: сжать в opus
(переиспользуем AudioCompressor), залить в S3, создать FileRecord(purpose='meeting_audio',
meeting_id=...). Без S3/FFmpeg — graceful (терминально, без ретрая), temp всегда чистится.
"""

import logging
import os
import shutil
import tempfile

from ...database import async_session
from ...models.file import FileRecord
from ...services import s3
from ...config import get_settings
from .audio_compressor import AudioCompressor

logger = logging.getLogger("meridian.batch")


async def handle_meeting_audio_archive(payload: dict) -> None:
    meeting_id = payload.get("meeting_id")
    user_id = payload.get("user_id")
    wav_path = payload.get("wav_path")

    if not wav_path or not os.path.exists(wav_path):
        logger.info("audio archive: wav отсутствует (%s) — пропуск", wav_path)
        return
    if user_id is None:
        logger.info("audio archive: meeting %s без владельца — пропуск, чищу wav", meeting_id)
        _safe_remove(wav_path)
        return

    settings = get_settings()
    if not settings.s3_enabled:
        # Без S3 не заливаем (терминально). Оставляем wav на диске для ручного разбора.
        logger.info("audio archive: S3 не настроен — wav %s оставлен на диске", wav_path)
        return

    tmpdir: str | None = None
    try:
        upload_path = wav_path
        ext = ".wav"
        mime = "audio/wav"

        compressor = AudioCompressor()
        if compressor.is_available:
            tmpdir = tempfile.mkdtemp(prefix="meridian_march_")
            res = await compressor.compress_to_opus(wav_path, tmpdir)
            if res:
                upload_path, _, _ = res
                ext = ".ogg"
                mime = "audio/ogg"
        else:
            logger.info("audio archive: FFmpeg недоступен — заливаю WAV без сжатия")

        key = s3.object_key(user_id, "meeting_audio", f"audio{ext}")
        await s3.upload_file(upload_path, key, content_type=mime)

        async with async_session() as db:
            db.add(FileRecord(
                user_id=user_id,
                object_key=key,
                original_name=f"meeting_{meeting_id}{ext}",
                size=os.path.getsize(upload_path),
                mime=mime,
                purpose="meeting_audio",
                status="active",
                meeting_id=meeting_id,
            ))
            await db.commit()
        logger.info("audio archive: meeting %s сохранён в S3 (%s)", meeting_id, key)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        _safe_remove(wav_path)


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
