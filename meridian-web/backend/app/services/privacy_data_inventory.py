"""Privacy data inventory (Этап 25).

Инвентаризация данных ОДНОЙ встречи: counts по категориям + безопасные ссылки (без raw
filename/S3 key/text). Здесь же — общая карта таблиц встречи и хелперы, которые переиспользуют
export- и delete-сервисы.

Безопасность: не читаем raw transcript/document text для inventory (только count/наличие).
safe_ref — вида `db:<category>:<count>` или `s3:<hash><ext>`.
"""

import hashlib
import os
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.meeting import (
    MeetingSession, TranscriptSegmentRecord, MeetingSuggestion,
    MeetingDocumentRecord, SavedTranscription,
)
from ..models.protocol import MeetingDecision, MeetingActionItem, MeetingRisk, MeetingOpenQuestion
from ..models.meeting_conversation import MeetingConversationTopic, MeetingSpeakerRole
from ..models.speaker_correction import MeetingSpeakerSegmentCorrection
from ..models.transcription_cutover import TranscriptionEpoch, MultiChannelSegmentRecord
from ..models.context_source import MeetingContextSource
from ..models.directory import MeetingParticipant
from ..models.knowledge import LearningCandidate
from ..models.file import FileRecord
from ..models.batch_job import BatchJob
from ..models.document import DocumentRecord, DocumentChunk
from ..models.job import Job

CATEGORIES = (
    "meeting", "transcript", "saved_transcription", "audio", "suggestion", "summary",
    "speaker_identity", "ai_settings_snapshot", "document", "meeting_document_link",
    "document_chunk", "participant", "meeting_context", "job", "learning", "trace",
    "storage_object", "unknown",
)

# (category, model, fk_attr) — CASCADE-child таблицы встречи (удаляются по fk).
# Категории выровнены с delete-планом; participant/meeting_context/saved_transcription — отдельные
# категории (Этап 26), чтобы их counts попадали в totals.
MEETING_CASCADE_TABLES: list[tuple[str, Any, str]] = [
    ("transcript", TranscriptSegmentRecord, "session_id"),
    ("transcript", MultiChannelSegmentRecord, "meeting_id"),
    ("transcript", TranscriptionEpoch, "meeting_id"),
    ("saved_transcription", SavedTranscription, "session_id"),
    ("suggestion", MeetingSuggestion, "session_id"),
    ("summary", MeetingDecision, "meeting_id"),
    ("summary", MeetingActionItem, "meeting_id"),
    ("summary", MeetingRisk, "meeting_id"),
    ("summary", MeetingOpenQuestion, "meeting_id"),
    ("summary", MeetingConversationTopic, "meeting_id"),
    ("speaker_identity", MeetingSpeakerRole, "meeting_id"),
    ("speaker_identity", MeetingSpeakerSegmentCorrection, "meeting_id"),
    ("meeting_context", MeetingContextSource, "meeting_id"),
    ("participant", MeetingParticipant, "meeting_id"),
    ("meeting_document_link", MeetingDocumentRecord, "session_id"),  # только link, не сам документ
]

# SET NULL таблицы — переживают удаление встречи, нужен explicit delete по fk.
MEETING_SETNULL_TABLES: list[tuple[str, Any, str]] = [
    ("learning", LearningCandidate, "meeting_id"),
    ("audio", BatchJob, "meeting_id"),
]

# MeetingSession-колонки со свободным текстом (чистятся при content-wipe, не удаляя запись).
MEETING_TEXT_COLUMNS = (
    "meeting_notes", "opponent_weaknesses", "micro_summary",
    "protocol_markdown", "protocol_json", "summary_json", "tags_json",
    "ai_settings_snapshot_json",
)


def hash_ref(value) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def storage_ref(key: str | None) -> str:
    if not key:
        return "none"
    ext = os.path.splitext(key)[1].lower()
    return f"s3:{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}{ext}"


class PrivacyDataItem(BaseModel):
    category: str
    count: int = 0
    storage_backend: str = "db"  # db | local | s3 | external | unknown
    safe_ref: str | None = None
    deletable: bool = False
    exportable: bool = False
    shared_reference: bool = False
    warning: str | None = None


class PrivacyInventoryReport(BaseModel):
    meeting_id: int | str
    user_id: int | str | None = None
    items: list[PrivacyDataItem] = []
    totals: dict = {}
    blockers: list[str] = []
    warnings: list[str] = []


async def _count(db: AsyncSession, model, fk_attr: str, meeting_id: int) -> int:
    col = getattr(model, fk_attr)
    return (await db.execute(select(func.count()).select_from(model).where(col == meeting_id))).scalar() or 0


async def meeting_document_ids(db: AsyncSession, meeting_id: int) -> list[int]:
    rows = (await db.execute(
        select(MeetingDocumentRecord.document_id).where(
            MeetingDocumentRecord.session_id == meeting_id,
            MeetingDocumentRecord.document_id.isnot(None),
        )
    )).scalars().all()
    return [d for d in rows if d is not None]


async def document_attachment_count(db: AsyncSession, document_id: int) -> int:
    return (await db.execute(
        select(func.count()).select_from(MeetingDocumentRecord).where(
            MeetingDocumentRecord.document_id == document_id)
    )).scalar() or 0


async def meeting_pending_jobs(db: AsyncSession, meeting_id: int, doc_ids: list[int]) -> list[Job]:
    """Pending/running jobs, относящиеся к встрече (payload meeting_id или document_id).

    Фильтруем в Python (payload — JSON, dialect-agnostic; таблица jobs небольшая)."""
    rows = (await db.execute(select(Job).where(Job.status.in_(["pending", "running"])))).scalars().all()
    out = []
    docset = set(doc_ids)
    for j in rows:
        p = j.payload or {}
        if p.get("meeting_id") == meeting_id or p.get("document_id") in docset:
            out.append(j)
    return out


async def meeting_audio_files(db: AsyncSession, meeting_id: int) -> list[FileRecord]:
    return list((await db.execute(
        select(FileRecord).where(
            FileRecord.meeting_id == meeting_id,
            FileRecord.purpose == "meeting_audio",
            FileRecord.status != "deleted",
        )
    )).scalars().all())


class PrivacyDataInventoryService:
    """Read-only инвентаризация данных встречи (counts + safe refs, без raw контента)."""

    async def build_meeting_inventory(self, db: AsyncSession, meeting_id: int,
                                      user=None) -> PrivacyInventoryReport:
        meeting = await db.get(MeetingSession, meeting_id)
        report = PrivacyInventoryReport(
            meeting_id=meeting_id, user_id=(getattr(user, "id", None)))
        if meeting is None:
            report.blockers.append("meeting_not_found")
            return report

        # агрегируем counts по категориям из CASCADE + SETNULL таблиц
        cat_counts: dict[str, int] = {}
        for category, model, fk in MEETING_CASCADE_TABLES + MEETING_SETNULL_TABLES:
            cat_counts[category] = cat_counts.get(category, 0) + await _count(db, model, fk, meeting_id)

        # meeting core (сама запись)
        report.items.append(PrivacyDataItem(
            category="meeting", count=1, storage_backend="db",
            safe_ref=f"db:meeting_sessions:{meeting_id and 1}", deletable=True, exportable=True))

        # transcript / suggestion / summary
        for category in ("transcript", "suggestion", "summary"):
            report.items.append(PrivacyDataItem(
                category=category, count=cat_counts.get(category, 0), storage_backend="db",
                safe_ref=f"db:{category}:{cat_counts.get(category, 0)}", deletable=True, exportable=True))

        # speaker_identity (+ hints в snapshot)
        si = cat_counts.get("speaker_identity", 0)
        has_hints = bool(meeting.ai_settings_snapshot_json and "speaker_identity_hints" in
                         (meeting.ai_settings_snapshot_json or ""))
        report.items.append(PrivacyDataItem(
            category="speaker_identity", count=si + (1 if has_hints else 0), storage_backend="db",
            safe_ref=f"db:speaker_identity:{si}", deletable=True, exportable=True,
            warning=("speaker_identity_hints stored inside ai_settings_snapshot_json" if has_hints else None)))

        # Этап 26: participant / meeting_context / saved_transcription — теперь в totals
        for category, tbl in (("participant", "meeting_participants"),
                              ("meeting_context", "meeting_context_sources"),
                              ("saved_transcription", "saved_transcriptions")):
            n = cat_counts.get(category, 0)
            report.items.append(PrivacyDataItem(
                category=category, count=n,
                storage_backend=("local" if category == "saved_transcription" else "db"),
                safe_ref=f"db:{tbl}:{n}", deletable=True,
                exportable=(category != "participant")))

        # ai_settings_snapshot (AI-настройки + speaker_identity_hints; в inventory только наличие/count)
        has_snapshot = bool(meeting.ai_settings_snapshot_json)
        report.items.append(PrivacyDataItem(
            category="ai_settings_snapshot", count=1 if has_snapshot else 0, storage_backend="db",
            safe_ref="db:meeting_sessions:ai_settings_snapshot", deletable=True, exportable=True,
            warning=("snapshot contains AI settings + speaker_identity_hints (no raw values in inventory)"
                     if has_snapshot else None)))

        # documents (shared-aware) + chunks + storage objects
        doc_ids = await meeting_document_ids(db, meeting_id)
        link_count = cat_counts.get("meeting_document_link", 0)
        shared = False
        s3_objects = 0
        chunk_total = 0
        for did in doc_ids:
            doc = await db.get(DocumentRecord, did)
            if doc is None:
                continue
            if await document_attachment_count(db, did) > 1:
                shared = True
            if doc.s3_key:
                s3_objects += 1
            chunk_total += (await db.execute(
                select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == did))
            ).scalar() or 0
        report.items.append(PrivacyDataItem(
            category="document", count=link_count, storage_backend="s3",
            safe_ref=f"db:meeting_documents:{link_count}",
            deletable=not shared, exportable=True, shared_reference=shared,
            warning=("some documents are attached to other meetings (shared) — not auto-deleted"
                     if shared else None)))
        report.items.append(PrivacyDataItem(
            category="document_chunk", count=chunk_total, storage_backend="db",
            safe_ref=f"db:document_chunks:{chunk_total}", deletable=not shared, exportable=False,
            shared_reference=shared))

        # audio (meeting_audio files + batch jobs + local audio_path)
        audio_files = await meeting_audio_files(db, meeting_id)
        batch_count = cat_counts.get("audio", 0)  # BatchJob
        local_audio = 1 if meeting.audio_path else 0
        s3_objects += len(audio_files)
        report.items.append(PrivacyDataItem(
            category="audio", count=len(audio_files) + batch_count + local_audio,
            storage_backend="s3" if audio_files else ("local" if local_audio else "db"),
            safe_ref=f"db:audio:{len(audio_files) + batch_count}", deletable=True, exportable=False,
            warning=("local meeting audio_path present" if local_audio else None)))

        # jobs
        jobs = await meeting_pending_jobs(db, meeting_id, doc_ids)
        report.items.append(PrivacyDataItem(
            category="job", count=len(jobs), storage_backend="db",
            safe_ref=f"db:jobs:{len(jobs)}", deletable=True, exportable=False))

        # learning (user-scoped — shared reference)
        learn = cat_counts.get("learning", 0)
        report.items.append(PrivacyDataItem(
            category="learning", count=learn, storage_backend="db",
            safe_ref=f"db:learning_candidates:{learn}", deletable=True, exportable=False,
            shared_reference=True,
            warning=("learning candidates are user-scoped knowledge (meeting_id link only)"
                     if learn else None)))

        # storage_object (aggregate s3 keys)
        report.items.append(PrivacyDataItem(
            category="storage_object", count=s3_objects, storage_backend="s3",
            safe_ref=f"s3:count:{s3_objects}", deletable=True, exportable=False))

        # trace (log-only, not app-managed)
        report.items.append(PrivacyDataItem(
            category="trace", count=0, storage_backend="external", safe_ref="external:app_log",
            deletable=False, exportable=False,
            warning="diagnostic traces are emitted to app.log only (log rotation, not app-managed)"))

        report.totals = {it.category: it.count for it in report.items}
        if shared:
            report.warnings.append("shared_documents_present")
        report.warnings.append("traces_are_external_log_only")
        return report
