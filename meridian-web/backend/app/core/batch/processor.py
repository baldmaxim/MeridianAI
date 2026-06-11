"""Идемпотентный обработчик батч-задачи (§16).

Возобновляемый по чекпоинтам BatchJob: compressed_path → transcription_json →
protocol_markdown. Повторный запуск после падения воркера не делает работу заново.
Терминальные ошибки (нет ключа, провайдер вернул пусто) → BatchJob.status='error' и
нормальный возврат (без ретрая). Неожиданные исключения пробрасываются — воркер
ретраит с backoff.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import select

from ...database import async_session
from ...models.batch_job import BatchJob
from ...services.api_keys import load_api_keys
from .audio_compressor import AudioCompressor
from .transcription_service import BatchTranscriptionService
from .protocol_generator import ProtocolGenerator
from .utils import split_protocol_output

logger = logging.getLogger("meridian.batch")


async def handle_batch_transcribe(payload: dict) -> None:
    job_id = payload["batch_job_id"]
    api_keys = await load_api_keys()

    async with async_session() as db:
        job = (
            await db.execute(select(BatchJob).where(BatchJob.id == job_id))
        ).scalar_one_or_none()
        if not job:
            logger.warning("batch job %s not found", job_id)
            return
        if job.status == "done":
            return  # идемпотентность: уже выполнено

        file_to_transcribe = job.compressed_path or job.file_path

        # Step 1: compress (пропуск, если уже сжато)
        if not job.compressed_path:
            ext = Path(job.file_path).suffix.lower()
            if ext not in {".ogg", ".opus"}:
                compressor = AudioCompressor()
                if compressor.is_available:
                    job.status = "compressing"
                    await db.commit()
                    res = await compressor.compress_to_opus(
                        job.file_path, str(Path(job.file_path).parent)
                    )
                    if res:
                        compressed_path, _, compressed_size = res
                        job.compressed_path = compressed_path
                        job.compressed_size = compressed_size
                        file_to_transcribe = compressed_path
                        await db.commit()
                else:
                    logger.info("FFmpeg недоступен — пропуск сжатия")

        # Step 2: transcribe (пропуск, если уже есть транскрипция)
        if not job.transcription_json:
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

        # Step 3: protocol (пропуск, если уже есть)
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
