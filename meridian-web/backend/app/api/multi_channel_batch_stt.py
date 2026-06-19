"""Batch multi-channel STT API (Этап 9.5).

POST   /api/meetings/{meeting_id}/multi-source/batch-stt   → 202 + job
GET    /api/meetings/{meeting_id}/multi-source/batch-stt/{job_id}
DELETE /api/meetings/{meeting_id}/multi-source/batch-stt/{job_id}

Только диагностический кандидат: live transcript не заменяется, ничего не сохраняется в
БД/диск/S3, API key/raw response/audio не логируются и не отдаются клиенту.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.meeting import MeetingSession
from ..config import get_settings
from ..services.access import can_record_meeting
from ..services.api_keys import load_api_keys
from ..services.meeting_room import room_registry
from ..services.speaker_roles import to_public_side
from ..services.multi_channel_wav import MultiChannelExportError
from ..services.multi_channel_export_service import (
    prepare_multi_channel_audio, build_prepared_wav,
)
from ..services.deepgram_multi_channel_batch import DeepgramMultiChannelBatchProvider
from ..services.multi_channel_transcript_compare import compare_batch_with_live
from ..services.multi_channel_batch_jobs import (
    batch_job_registry, ActiveJobExistsError, MultiChannelBatchJob,
)
from ..schemas.multi_channel_batch_stt import MultiChannelBatchSttRequest
from .multi_channel_export import _ERROR_STATUS

router = APIRouter()
logger = logging.getLogger("meridian.batch_stt_api")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _word_out(w) -> dict:
    return {"text": w.text, "start": w.start, "end": w.end, "channel_index": w.channel_index,
            "confidence": w.confidence, "punctuated_word": w.punctuated_word}


def _seg_out(s) -> dict:
    return {"segment_id": s.segment_id, "channel_index": s.channel_index, "track_id": s.track_id,
            "channel_label": s.channel_label, "side": s.side, "text": s.text,
            "start": s.start, "end": s.end, "confidence": s.confidence,
            "words": [_word_out(w) for w in s.words]}


def _result_out(r) -> dict | None:
    if r is None:
        return None
    return {
        "provider": r.provider, "model": r.model, "language": r.language,
        "provider_request_id": r.provider_request_id, "sample_rate": r.sample_rate,
        "channels_count": r.channels_count, "duration_ms": r.duration_ms,
        "channels": [{
            "channel_index": c.channel_index, "track_id": c.track_id,
            "channel_label": c.channel_label, "side": c.side, "source_kind": c.source_kind,
            "generation": c.generation, "transcript": c.transcript,
            "words_count": c.words_count, "segments_count": c.segments_count,
            "average_confidence": c.average_confidence,
            "segments": [_seg_out(s) for s in c.segments], "warnings": list(c.warnings),
        } for c in r.channels],
        "chronological_segments": [_seg_out(s) for s in r.chronological_segments],
        "combined_text": r.combined_text, "warnings": list(r.warnings),
        "provider_meta": r.provider_meta,  # ТОЛЬКО request_id/model/lang/duration/channels
    }


def _job_out(job: MultiChannelBatchJob) -> dict:
    return {
        "job_id": job.job_id, "meeting_id": job.meeting_id, "status": job.status,
        "stage": job.stage, "progress": job.progress, "provider": job.provider,
        "model": job.model, "language": job.language,
        "created_at": _iso(job.created_at), "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at), "expires_at": _iso(job.expires_at),
        "result": _result_out(job.result), "comparison": job.comparison,
        "export_manifest": job.export_manifest,
        "error_code": job.error_code, "error_message": job.error_message,
        "retryable": job.retryable,
    }


async def _require_meeting_and_access(meeting_id: int, user: User, db: AsyncSession):
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        raise HTTPException(404, detail={"code": "MEETING_NOT_FOUND", "message": "Встреча не найдена"})
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Нет доступа к записи встречи"})


@router.post("/{meeting_id}/multi-source/batch-stt", status_code=202)
async def start_batch_stt(meeting_id: int, req: MultiChannelBatchSttRequest,
                          user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if not settings.multi_channel_batch_stt_enabled:
        raise HTTPException(503, detail={"code": "FEATURE_DISABLED", "message": "Batch STT выключен"})
    if settings.multi_channel_batch_stt_provider != "deepgram":
        raise HTTPException(503, detail={"code": "UNSUPPORTED_PROVIDER",
                                         "message": "Провайдер не поддерживается"})

    await _require_meeting_and_access(meeting_id, user, db)

    keys = await load_api_keys()
    dg_key = keys.get("deepgram", "")
    if not dg_key:
        raise HTTPException(503, detail={"code": "PROVIDER_NOT_CONFIGURED",
                                         "message": "STT-провайдер не настроен"})

    room = room_registry.get_room(meeting_id)
    if room is None or not getattr(room, "ingest", None):
        raise HTTPException(409, detail={"code": "NO_ROOM", "message": "Активная сессия встречи не найдена"})

    # --- синхронный блок: snapshot + live-копия атомарны к ingest/сессии ---
    try:
        prepared = prepare_multi_channel_audio(
            room=room, request=req.export, settings=settings,
            meeting_id=meeting_id, created_at=datetime.now(timezone.utc),
        )
    except MultiChannelExportError as e:
        raise HTTPException(_ERROR_STATUS.get(e.code, 422),
                            detail={"code": e.code, "message": str(e)})

    plan = prepared.plan
    if plan.channel_count < settings.multi_channel_batch_stt_min_channels:
        raise HTTPException(422, detail={"code": "INVALID_CHANNEL_COUNT",
                                         "message": "Нужно минимум 2 канала"})
    if plan.channel_count > settings.multi_channel_batch_stt_max_channels:
        raise HTTPException(422, detail={"code": "INVALID_CHANNEL_COUNT",
                                         "message": "Слишком много каналов"})
    if plan.duration_ms < settings.multi_channel_batch_stt_min_duration_seconds * 1000:
        raise HTTPException(422, detail={"code": "INVALID_AUDIO",
                                         "message": "Слишком короткое окно для распознавания"})
    if plan.duration_ms > settings.multi_channel_batch_stt_max_seconds * 1000:
        raise HTTPException(413, detail={"code": "DURATION_LIMIT", "message": "Окно слишком длинное"})
    if plan.wav_bytes > settings.multi_channel_batch_stt_max_wav_bytes:
        raise HTTPException(413, detail={"code": "BYTE_LIMIT", "message": "WAV слишком большой"})

    # side overrides (приоритет: request override → track side_hint → null)
    effective_mapping = []
    for m in prepared.channel_mapping:
        tid = m["track_id"]
        if tid in req.channel_side_overrides:
            side = to_public_side(req.channel_side_overrides[tid])
        else:
            side = m["side_hint"]
        effective_mapping.append({
            "channel_index": m["channel_index"], "track_id": tid,
            "channel_label": m["channel_label"], "side": side,
            "source_kind": m["source_kind"], "generation": m["generation"],
        })

    # live committed segments (read-only копия для сравнения)
    live_lite: list[dict] = []
    if req.compare_with_live:
        try:
            for seg in list(room.session.committed_segments):
                try:
                    _spk, side = room.session._resolve_segment(seg)
                except Exception:
                    side = None
                live_lite.append({"text": getattr(seg, "text", "") or "", "side": side})
        except Exception:
            live_lite = []

    provider = DeepgramMultiChannelBatchProvider(
        api_key=dg_key, base_url=settings.deepgram_batch_url,
        max_response_bytes=settings.multi_channel_batch_stt_max_response_bytes,
    )
    channel_count = plan.channel_count
    language = settings.multi_channel_batch_stt_language
    model = settings.multi_channel_batch_stt_model
    timeout = settings.multi_channel_batch_stt_timeout_seconds
    compare_flag = req.compare_with_live

    async def runner(job: MultiChannelBatchJob) -> None:
        job.export_manifest = prepared.manifest
        job.stage = "preparing"
        job.progress = 0.1
        wav = await build_prepared_wav(prepared)
        try:
            job.stage = "transcribing"
            job.progress = 0.4
            result = await provider.transcribe(
                wav_bytes=wav, channel_count=channel_count, channel_mapping=effective_mapping,
                language=language, model=model, timeout_seconds=timeout,
            )
        finally:
            wav = None  # освобождаем крупную ссылку
        job.stage = "parsing"
        job.progress = 0.8
        job.result = result
        if compare_flag:
            job.stage = "comparing"
            job.progress = 0.9
            job.comparison = compare_batch_with_live(batch_result=result, live_segments=live_lite)

    try:
        job = await batch_job_registry.create_job(
            meeting_id=meeting_id, user_id=user.id, provider="deepgram",
            model=model, language=language,
            ttl_seconds=settings.multi_channel_batch_stt_result_ttl_seconds,
            max_global_jobs=settings.multi_channel_batch_stt_max_global_jobs,
            runner=runner,
        )
    except ActiveJobExistsError as e:
        raise HTTPException(409, detail={"code": "ACTIVE_JOB_EXISTS", "message": str(e)})

    return JSONResponse(status_code=202, content=_job_out(job))


@router.get("/{meeting_id}/multi-source/batch-stt/{job_id}")
async def get_batch_stt(meeting_id: int, job_id: str,
                        user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _require_meeting_and_access(meeting_id, user, db)
    job = await batch_job_registry.get_job(job_id)
    if job is None or job.meeting_id != meeting_id:
        raise HTTPException(404, detail={"code": "JOB_NOT_FOUND", "message": "Job не найден"})
    if job.owner_user_id != user.id and not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Нет доступа к job"})
    if job.status == "expired":
        raise HTTPException(410, detail={"code": "EXPIRED", "message": "Результат истёк"})
    return JSONResponse(content=_job_out(job))


@router.delete("/{meeting_id}/multi-source/batch-stt/{job_id}")
async def cancel_batch_stt(meeting_id: int, job_id: str,
                           user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    await _require_meeting_and_access(meeting_id, user, db)
    job = await batch_job_registry.get_job(job_id)
    if job is None or job.meeting_id != meeting_id:
        raise HTTPException(404, detail={"code": "JOB_NOT_FOUND", "message": "Job не найден"})
    if job.owner_user_id != user.id and not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Нет доступа к job"})
    await batch_job_registry.cancel_job(job_id)
    return JSONResponse(content={"cancelled": True, "job_id": job_id})
