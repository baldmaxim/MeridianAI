"""Local storage utility — copies meeting documents and transcription to a local folder."""

import json
import logging
import os
import re
import shutil
from datetime import datetime

from sqlalchemy import select

from ..database import async_session
from ..models.settings import UserSettings
from ..models.meeting import MeetingSession, TranscriptSegmentRecord, MeetingDocumentRecord
from ..config import get_settings

logger = logging.getLogger("ai_helper.local_storage")


def _safe_folder_name(name: str, max_len: int = 80) -> str:
    """Sanitize string for use as folder name."""
    safe = re.sub(r'[<>:"/\\|?*]', '_', name)
    safe = safe.strip('. ')
    return safe[:max_len] if safe else "meeting"


async def save_meeting_to_local(user_id: int, meeting_id: int) -> str | None:
    """Copy meeting documents and transcription to user's local_storage_path.

    Returns the created folder path, or None if local_storage_path is not set.
    """
    async with async_session() as db:
        # 1. Load user settings
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        user_settings = result.scalar_one_or_none()
        if not user_settings or not user_settings.local_storage_path:
            return None

        base_path = user_settings.local_storage_path.strip()
        if not base_path:
            return None

        # 2. Load meeting
        result = await db.execute(
            select(MeetingSession).where(MeetingSession.id == meeting_id)
        )
        meeting = result.scalar_one_or_none()
        if not meeting:
            logger.warning(f"Meeting {meeting_id} not found for local save")
            return None

        # 3. Create folder structure
        safe_title = _safe_folder_name(meeting.title or f"meeting_{meeting_id}")
        meeting_dir = os.path.join(base_path, f"{meeting_id}_{safe_title}")
        docs_dir = os.path.join(meeting_dir, "documents")

        try:
            os.makedirs(docs_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Cannot create local folder {meeting_dir}: {e}")
            return None

        # 4. Copy documents
        cfg = get_settings()
        doc_result = await db.execute(
            select(MeetingDocumentRecord).where(
                MeetingDocumentRecord.session_id == meeting_id
            )
        )
        for doc in doc_result.scalars().all():
            src = os.path.join(cfg.upload_dir, str(user_id), doc.filename)
            if os.path.exists(src):
                try:
                    shutil.copy2(src, os.path.join(docs_dir, doc.filename))
                except OSError as e:
                    logger.error(f"Failed to copy {src}: {e}")

        # 5. Save transcription
        seg_result = await db.execute(
            select(TranscriptSegmentRecord)
            .where(TranscriptSegmentRecord.session_id == meeting_id)
            .order_by(TranscriptSegmentRecord.wall_clock.asc())
        )
        lines = []
        for seg in seg_result.scalars().all():
            time_str = seg.wall_clock.strftime("%H:%M:%S") if seg.wall_clock else ""
            speaker = seg.speaker_label or seg.speaker_id or "?"
            lines.append(f"[{time_str}] {speaker}: {seg.text}")

        if lines:
            try:
                with open(os.path.join(meeting_dir, "transcription.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except OSError as e:
                logger.error(f"Failed to write transcription: {e}")

        # 6. Save context.json
        context = {
            "meeting_id": meeting_id,
            "title": meeting.title,
            "meeting_topic": meeting.meeting_topic,
            "meeting_notes": meeting.meeting_notes,
            "negotiation_type": meeting.negotiation_type,
            "meeting_role": meeting.meeting_role,
            "opponent_weaknesses": meeting.opponent_weaknesses,
            "started_at": meeting.started_at.isoformat() if meeting.started_at else None,
            "ended_at": meeting.ended_at.isoformat() if meeting.ended_at else None,
        }
        try:
            with open(os.path.join(meeting_dir, "context.json"), "w", encoding="utf-8") as f:
                json.dump(context, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"Failed to write context.json: {e}")

        logger.info(f"Meeting {meeting_id} saved to local: {meeting_dir}")
        return meeting_dir
