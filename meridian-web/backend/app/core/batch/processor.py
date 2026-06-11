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
from pathlib import Path

from sqlalchemy import select

from ...database import async_session
from ...models.batch_job import BatchJob
from ...services.api_keys import load_api_keys
from ...services import s3
from .audio_compressor import AudioCompressor
from .transcription_service import BatchTranscriptionService
from .protocol_generator import ProtocolGenerator
from .utils import split_protocol_output

logger = logging.getLogger("meridian.batch")


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

            # Транскрипция (с предшествующими download + compress) — только если ещё нет
            if not job.transcription_json:
                tmpdir = tempfile.mkdtemp(prefix="meridian_batch_")
                # file_path = локальный путь (fallback) ИЛИ S3-ключ (presigned)
                if os.path.exists(job.file_path):
                    local_audio = job.file_path
                else:
                    local_audio = os.path.join(
                        tmpdir, os.path.basename(job.original_filename) or "audio"
                    )
                    await s3.download_to(job.file_path, local_audio)
                file_to_transcribe = local_audio

                # сжатие (опционально, в temp)
                ext = Path(job.original_filename).suffix.lower()
                if ext not in {".ogg", ".opus"}:
                    compressor = AudioCompressor()
                    if compressor.is_available:
                        job.status = "compressing"
                        await db.commit()
                        res = await compressor.compress_to_opus(local_audio, tmpdir)
                        if res:
                            compressed_path, _, compressed_size = res
                            job.compressed_size = compressed_size
                            file_to_transcribe = compressed_path
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
