"""Privacy export manifest (Этап 25).

V1: безопасный JSON-манифест данных ОДНОЙ встречи (метаданные + текстовый контент встречи, который
и так виден пользователю: транскрипт/подсказки/протокол/роли). RAW документы/аудио байтами в v1 НЕ
бандлятся (JSON-only, без ZIP) — только метаданные/counts. НИКОГДА: S3 key, presigned URL, raw
filename, внутренние пути. Транскрипт-текст — легитимный экспорт-контент, но в ЛОГИ не попадает.
"""

import json
import logging
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.meeting import MeetingSession, TranscriptSegmentRecord, MeetingSuggestion
from ..models.protocol import MeetingDecision, MeetingActionItem, MeetingRisk, MeetingOpenQuestion
from ..models.meeting_conversation import MeetingSpeakerRole
from ..core.privacy.privacy_audit import log_privacy_event
from . import privacy_data_inventory as inv

logger = logging.getLogger("meridian.privacy")

_MAX_SEGMENTS = 20000  # защитный предел размера экспорта


class PrivacyExportManifest(BaseModel):
    meeting_id: int | str
    created_at: str
    sections: list[str] = []
    counts: dict = {}
    includes_raw_documents: bool = False
    includes_raw_audio: bool = False
    warnings: list[str] = []
    data: dict = {}


class PrivacyExportService:
    async def build_export_manifest(self, db: AsyncSession, meeting_id: int, user=None, *,
                                    include_documents: bool = False,
                                    include_audio: bool = False) -> PrivacyExportManifest:
        now = datetime.utcnow().isoformat() + "Z"
        m = await db.get(MeetingSession, meeting_id)
        manifest = PrivacyExportManifest(meeting_id=meeting_id, created_at=now)
        if m is None:
            manifest.warnings.append("meeting_not_found")
            return manifest

        # 1) meeting metadata (безопасные поля — это контент самого пользователя)
        manifest.data["meeting"] = {
            "id": m.id,
            "title": m.title,
            "meeting_topic": m.meeting_topic,
            "negotiation_type": m.negotiation_type,
            "meeting_role": m.meeting_role,
            "status": m.status,
            "finalization_status": m.finalization_status,
            "learning_status": m.learning_status,
            "started_at": m.started_at.isoformat() if m.started_at else None,
            "ended_at": m.ended_at.isoformat() if m.ended_at else None,
            "recorded_seconds": m.recorded_seconds,
        }

        # 2) transcript (текст — легитимный экспорт-контент)
        segs = list((await db.execute(
            select(TranscriptSegmentRecord).where(TranscriptSegmentRecord.session_id == meeting_id)
            .order_by(TranscriptSegmentRecord.start_time).limit(_MAX_SEGMENTS)
        )).scalars().all())
        manifest.data["transcript"] = [
            {"segment_id": s.segment_id, "speaker_label": s.speaker_label, "side": None,
             "start_time": s.start_time, "end_time": s.end_time, "text": s.text}
            for s in segs
        ]

        # 3) suggestions / cards
        sugg = list((await db.execute(
            select(MeetingSuggestion).where(MeetingSuggestion.session_id == meeting_id)
            .order_by(MeetingSuggestion.created_at)
        )).scalars().all())
        manifest.data["suggestions"] = [
            {"type": s.suggestion_type, "title": s.title, "text": s.text, "why": s.why,
             "is_auto": s.is_auto, "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in sugg
        ]

        # 4) summary / protocol
        manifest.data["summary"] = {
            "protocol_markdown": m.protocol_markdown,
            "summary_json": _load_json(m.summary_json),
            "micro_summary": m.micro_summary,
            "decisions": await _texts(db, MeetingDecision, meeting_id, "text"),
            "action_items": await _texts(db, MeetingActionItem, meeting_id, "task"),
            "risks": await _texts(db, MeetingRisk, meeting_id, "text"),
            "open_questions": await _texts(db, MeetingOpenQuestion, meeting_id, "text"),
        }

        # 5) speaker roles (labels/sides — не PII)
        roles = list((await db.execute(
            select(MeetingSpeakerRole).where(MeetingSpeakerRole.meeting_id == meeting_id)
        )).scalars().all())
        manifest.data["speaker_roles"] = [
            {"speaker_label": r.speaker_label, "side": r.side} for r in roles
        ]

        # 6) documents — только метаданные (без raw filename/S3 key); raw байты в v1 не бандлятся
        doc_ids = await inv.meeting_document_ids(db, meeting_id)
        docs_meta = []
        for did in doc_ids:
            doc = await db.get(inv.DocumentRecord, did)
            if doc is None:
                continue
            docs_meta.append({
                "document_id": did, "file_ext": doc.file_ext, "status": doc.status,
                "page_count": doc.page_count, "safe_ref": inv.storage_ref(doc.s3_key),
                "name_hash": inv.hash_ref(doc.original_name) if doc.original_name else None,
            })
        manifest.data["documents"] = docs_meta

        # 7) audio — только метаданные
        audio_files = await inv.meeting_audio_files(db, meeting_id)
        manifest.data["audio"] = {
            "recorded_seconds": m.recorded_seconds,
            "meeting_audio_files": len(audio_files),
            "has_local_audio_path": bool(m.audio_path),
        }

        # raw-бандлинг в v1 не поддержан
        if include_documents:
            manifest.warnings.append("include_documents requested; raw document bundling not in v1 (metadata only)")
        if include_audio:
            manifest.warnings.append("include_audio requested; raw audio bundling not in v1 (metadata only)")
        manifest.includes_raw_documents = False
        manifest.includes_raw_audio = False

        manifest.sections = ["meeting", "transcript", "suggestions", "summary",
                             "speaker_roles", "documents", "audio"]
        manifest.counts = {
            "transcript": len(segs), "suggestions": len(sugg), "documents": len(docs_meta),
            "speaker_roles": len(roles), "audio_files": len(audio_files),
        }
        # безопасный лог: только секции + counts (без текста/имён)
        log_privacy_event(logger, "privacy_export_created", meeting_id=meeting_id,
                          user_id=getattr(user, "id", None), counts=manifest.counts,
                          warnings=manifest.warnings)
        return manifest


def _load_json(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def _texts(db: AsyncSession, model, meeting_id: int, attr: str) -> list[str]:
    rows = list((await db.execute(
        select(model).where(model.meeting_id == meeting_id)
    )).scalars().all())
    return [getattr(r, attr) for r in rows if getattr(r, attr, None)]
