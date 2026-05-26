"""Meeting transcription save/export API routes."""

import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, async_session
from ..models.user import User
from ..models.meeting import SavedTranscription
from ..schemas.meeting import SaveTranscriptionRequest, TranscriptionResponse
from ..auth.dependencies import get_current_user
from ..auth.service import decode_token
from ..config import get_settings
from ..services.session_manager import get_session_manager

router = APIRouter()


@router.post("/save", response_model=TranscriptionResponse)
async def save_transcription(
    data: SaveTranscriptionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save current transcription as TXT or JSON."""
    session = get_session_manager(user.id)
    history = session.context_analyzer.full_history

    if not history:
        raise HTTPException(status_code=400, detail="No transcription data to save")

    settings = get_settings()
    user_dir = os.path.join(settings.transcription_dir, str(user.id))
    os.makedirs(user_dir, exist_ok=True)

    date_str = datetime.now().strftime("%d_%m_%Y")
    safe_name = data.filename.replace("/", "_").replace("\\", "_")

    if data.format == "txt":
        filename = f"{safe_name}_{date_str}.txt"
        file_path = os.path.join(user_dir, filename)
        lines = []
        for seg in history:
            time_str = seg.timestamp.strftime("%H:%M:%S")
            lines.append(f"[{time_str}] {seg.speaker}: {seg.text}")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    elif data.format == "json":
        filename = f"{safe_name}_{date_str}.json"
        file_path = os.path.join(user_dir, filename)
        segments = [
            {
                "speaker": seg.speaker,
                "text": seg.text,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "timestamp": seg.timestamp.isoformat(),
                "confidence": seg.confidence,
            }
            for seg in history
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "saved_at": datetime.now().isoformat(),
                    "segment_count": len(segments),
                    "segments": segments,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    else:
        raise HTTPException(status_code=400, detail="Format must be 'txt' or 'json'")

    record = SavedTranscription(
        user_id=user.id,
        filename=filename,
        format=data.format,
        file_path=file_path,
        segment_count=len(history),
    )
    db.add(record)
    await db.flush()

    return record


@router.get("", response_model=list[TranscriptionResponse])
async def list_transcriptions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List saved transcriptions."""
    result = await db.execute(
        select(SavedTranscription)
        .where(SavedTranscription.user_id == user.id)
        .order_by(SavedTranscription.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{transcription_id}/download")
async def download_transcription(
    transcription_id: int,
    token: str = Query(...),
):
    """Download a saved transcription file. Uses query token for direct link access."""
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = int(payload["sub"])

    async with async_session() as db:
        result = await db.execute(
            select(SavedTranscription).where(
                SavedTranscription.id == transcription_id,
                SavedTranscription.user_id == user_id,
            )
        )
        record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Transcription not found")

    if not os.path.exists(record.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    media_type = "text/plain" if record.format == "txt" else "application/json"
    return FileResponse(
        record.file_path,
        filename=record.filename,
        media_type=media_type,
    )
