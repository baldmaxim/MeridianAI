"""Privacy delete plan + guarded hard-delete for ONE meeting (Этап 25).

Safe-by-default: dry-run всегда доступен; реальное удаление требует
PRIVACY_HARD_DELETE_ENABLED=true И (при PRIVACY_DELETE_REQUIRE_DRY_RUN_FIRST) валидный
HMAC-подписанный confirmation_token из dry-run плана. Shared-документы НЕ удаляются вслепую.
Локальное удаление — только под разрешёнными директориями (path-traversal guard). S3 — только через
document_storage. НИКОГДА не логируем raw text/filename/S3 key/URL.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..core.privacy.privacy_audit import log_privacy_event
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
from . import document_storage
from . import privacy_data_inventory as inv

logger = logging.getLogger("meridian.privacy")

# CASCADE-child таблицы, которые всегда чистим при wipe (кроме link/participants — они особые).
_CONTENT_TABLES: list[tuple[str, object, str]] = [
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
    ("learning", LearningCandidate, "meeting_id"),
]


class PrivacyDeleteItem(BaseModel):
    category: str
    count: int = 0
    action: str  # delete_db_rows | delete_local_file | delete_s3_object | cancel_job | skip_shared | skip_unsupported
    safe_ref: str | None = None
    will_delete: bool = False
    reason: str | None = None


class PrivacyDeletePlan(BaseModel):
    meeting_id: int | str
    dry_run: bool = True
    items: list[PrivacyDeleteItem] = []
    blockers: list[str] = []
    warnings: list[str] = []
    requires_confirmation: bool = False
    hard_delete_enabled: bool = False
    confirmation_token: str | None = None


class PrivacyDeleteExecutionReport(BaseModel):
    meeting_id: int | str
    executed: bool = False
    dry_run: bool = True
    deleted_counts: dict = {}
    errors: list[str] = []
    partial_delete: bool = False
    blockers: list[str] = []


def _make_confirmation_token(meeting_id: int, user_id, flags: dict) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=int(s.privacy_confirmation_ttl_minutes))
    payload = {
        "typ": "privacy_delete", "meeting_id": meeting_id, "user_id": user_id,
        "d": bool(flags["include_documents"]), "a": bool(flags["include_audio"]),
        "m": bool(flags["include_meeting_record"]), "exp": exp,
    }
    return jwt.encode(payload, s.privacy_confirmation_key_effective, algorithm="HS256")


def verify_confirmation_token(token: str | None, meeting_id: int, user_id, flags: dict) -> tuple[bool, str]:
    if not token:
        return False, "confirmation_token_missing"
    s = get_settings()
    try:
        p = jwt.decode(token, s.privacy_confirmation_key_effective, algorithms=["HS256"])
    except JWTError:
        return False, "confirmation_token_invalid_or_expired"
    if p.get("typ") != "privacy_delete":
        return False, "confirmation_token_wrong_type"
    if p.get("meeting_id") != meeting_id:
        return False, "confirmation_token_meeting_mismatch"
    if user_id is not None and p.get("user_id") != user_id:
        return False, "confirmation_token_user_mismatch"
    if (bool(p.get("d")) != bool(flags["include_documents"])
            or bool(p.get("a")) != bool(flags["include_audio"])
            or bool(p.get("m")) != bool(flags["include_meeting_record"])):
        return False, "confirmation_token_flags_mismatch"
    return True, "ok"


def _allowed_local_bases() -> list[str]:
    s = get_settings()
    bases = []
    for b in (s.upload_dir, getattr(s, "transcription_dir", None)):
        if b:
            bases.append(os.path.realpath(b))
    return bases


def _is_under_allowed(path: str) -> bool:
    real = os.path.realpath(path)
    for base in _allowed_local_bases():
        try:
            if os.path.commonpath([real, base]) == base:
                return True
        except ValueError:
            continue
    return False


class PrivacyDeleteService:

    async def build_delete_plan(self, db: AsyncSession, meeting_id: int, user=None, *,
                                include_documents: bool = True, include_audio: bool = True,
                                include_meeting_record: bool = False) -> PrivacyDeletePlan:
        s = get_settings()
        flags = {"include_documents": include_documents, "include_audio": include_audio,
                 "include_meeting_record": include_meeting_record}
        plan = PrivacyDeletePlan(
            meeting_id=meeting_id, dry_run=True,
            hard_delete_enabled=bool(s.privacy_hard_delete_enabled),
            requires_confirmation=bool(s.privacy_delete_require_dry_run_first))
        m = await db.get(MeetingSession, meeting_id)
        if m is None:
            plan.blockers.append("meeting_not_found")
            return plan

        # content-таблицы (counts)
        for category, model, fk in _CONTENT_TABLES:
            n = await inv._count(db, model, fk, meeting_id)
            if n:
                plan.items.append(PrivacyDeleteItem(
                    category=category, count=n, action="delete_db_rows",
                    safe_ref=f"db:{model.__tablename__}:{n}", will_delete=True,
                    reason="meeting_scoped"))

        # meeting text-columns wipe
        plan.items.append(PrivacyDeleteItem(
            category="meeting", count=1, action="delete_db_rows",
            safe_ref="db:meeting_sessions:text_columns", will_delete=True,
            reason=("delete_meeting_record" if include_meeting_record else "clear_text_columns")))

        # ai_settings_snapshot (в т.ч. speaker_identity_hints) — очищается при wipe (Этап 26 alignment)
        if m.ai_settings_snapshot_json:
            plan.items.append(PrivacyDeleteItem(
                category="ai_settings_snapshot", count=1, action="delete_db_rows",
                safe_ref="db:meeting_sessions:ai_settings_snapshot", will_delete=True,
                reason="clear_snapshot"))

        # jobs
        doc_ids = await inv.meeting_document_ids(db, meeting_id)
        jobs = await inv.meeting_pending_jobs(db, meeting_id, doc_ids)
        if jobs:
            plan.items.append(PrivacyDeleteItem(
                category="job", count=len(jobs), action="cancel_job",
                safe_ref=f"db:jobs:{len(jobs)}", will_delete=True, reason="pending_meeting_jobs"))

        # documents (shared-aware)
        for did in doc_ids:
            doc = await db.get(DocumentRecord, did)
            if doc is None:
                continue
            shared = await inv.document_attachment_count(db, did) > 1
            if not include_documents:
                plan.items.append(PrivacyDeleteItem(
                    category="document", count=1, action="delete_db_rows",
                    safe_ref=inv.storage_ref(doc.s3_key), will_delete=True,
                    reason="detach_link_only (include_documents=false)"))
            elif shared:
                plan.items.append(PrivacyDeleteItem(
                    category="document", count=1, action="skip_shared",
                    safe_ref=inv.storage_ref(doc.s3_key), will_delete=False,
                    reason="attached_to_other_meetings"))
            else:
                plan.items.append(PrivacyDeleteItem(
                    category="document", count=1, action="delete_s3_object",
                    safe_ref=inv.storage_ref(doc.s3_key), will_delete=True,
                    reason="meeting_scoped_document"))

        # audio
        if include_audio:
            audio_files = await inv.meeting_audio_files(db, meeting_id)
            if audio_files:
                plan.items.append(PrivacyDeleteItem(
                    category="audio", count=len(audio_files), action="delete_s3_object",
                    safe_ref=f"s3:count:{len(audio_files)}", will_delete=True, reason="meeting_audio"))
            batch = await inv._count(db, BatchJob, "meeting_id", meeting_id)
            if batch:
                plan.items.append(PrivacyDeleteItem(
                    category="audio", count=batch, action="delete_db_rows",
                    safe_ref=f"db:batch_jobs:{batch}", will_delete=True, reason="batch_jobs"))
            if m.audio_path:
                under = _is_under_allowed(m.audio_path)
                plan.items.append(PrivacyDeleteItem(
                    category="audio", count=1,
                    action="delete_local_file" if under else "skip_unsupported",
                    safe_ref=f"local:{inv.hash_ref(m.audio_path)}", will_delete=under,
                    reason="local_audio_path" if under else "outside_allowed_dir"))

        # participants — только при полном удалении записи (категория выровнена с inventory)
        if include_meeting_record:
            pc = await inv._count(db, MeetingParticipant, "meeting_id", meeting_id)
            if pc:
                plan.items.append(PrivacyDeleteItem(
                    category="participant", count=pc, action="delete_db_rows",
                    safe_ref=f"db:meeting_participants:{pc}", will_delete=True, reason="participants"))

        if any(it.action == "skip_shared" for it in plan.items):
            plan.warnings.append("shared_documents_skipped")

        # confirmation token (только если hard delete включён)
        if plan.hard_delete_enabled:
            plan.confirmation_token = _make_confirmation_token(meeting_id, getattr(user, "id", None), flags)

        log_privacy_event(logger, "privacy_delete_plan_created", meeting_id=meeting_id,
                          user_id=getattr(user, "id", None),
                          counts={it.category: it.count for it in plan.items},
                          warnings=plan.warnings)
        return plan

    async def execute_delete_plan(self, db: AsyncSession, meeting_id: int, user=None, *,
                                  dry_run: bool = True, confirmation_token: str | None = None,
                                  include_documents: bool = True, include_audio: bool = True,
                                  include_meeting_record: bool = False) -> PrivacyDeleteExecutionReport:
        s = get_settings()
        flags = {"include_documents": include_documents, "include_audio": include_audio,
                 "include_meeting_record": include_meeting_record}
        rep = PrivacyDeleteExecutionReport(meeting_id=meeting_id, dry_run=dry_run)

        if dry_run:
            plan = await self.build_delete_plan(
                db, meeting_id, user, include_documents=include_documents,
                include_audio=include_audio, include_meeting_record=include_meeting_record)
            rep.deleted_counts = {it.category: it.count for it in plan.items if it.will_delete}
            rep.blockers = plan.blockers
            return rep

        # --- реальное удаление: строгие гейты ---
        if not s.privacy_controls_enabled:
            rep.blockers.append("privacy_controls_disabled")
            return rep
        if not s.privacy_hard_delete_enabled:
            rep.blockers.append("hard_delete_disabled")
            return rep
        if s.privacy_delete_require_dry_run_first:
            ok, reason = verify_confirmation_token(confirmation_token, meeting_id,
                                                   getattr(user, "id", None), flags)
            if not ok:
                rep.blockers.append(reason)
                return rep
        m = await db.get(MeetingSession, meeting_id)
        if m is None:
            rep.blockers.append("meeting_not_found")
            return rep

        counts: dict[str, int] = {}

        def _bump(cat, n):
            if n:
                counts[cat] = counts.get(cat, 0) + int(n)

        # 1) cancel pending jobs
        doc_ids = await inv.meeting_document_ids(db, meeting_id)
        try:
            jobs = await inv.meeting_pending_jobs(db, meeting_id, doc_ids)
            for j in jobs:
                j.status = "dead"
            _bump("job", len(jobs))
        except Exception as e:  # noqa: BLE001
            rep.errors.append(f"jobs:{type(e).__name__}")

        # 2) documents + chunks + S3 (shared-aware)
        for did in doc_ids:
            try:
                doc = await db.get(DocumentRecord, did)
                if doc is None:
                    continue
                shared = await inv.document_attachment_count(db, did) > 1
                if not include_documents:
                    continue  # только link удалим ниже (через content wipe meeting_documents)
                if shared:
                    continue  # skip_shared
                # S3 объекты (idempotent)
                for key in (doc.s3_key, doc.extracted_text_s3_key):
                    if key:
                        await document_storage.delete_object(key)
                        _bump("storage_object", 1)
                if doc.file_id:
                    fr = await db.get(FileRecord, doc.file_id)
                    if fr:
                        fr.status = "deleted"
                        if not fr.deleted_at:
                            fr.deleted_at = datetime.utcnow()
                await db.delete(doc)  # CASCADE снимает chunks + meeting_documents link
                _bump("document", 1)
            except Exception as e:  # noqa: BLE001
                rep.errors.append(f"document:{type(e).__name__}")

        # 3) meeting_documents links (оставшиеся, если documents не удалялись)
        try:
            res = await db.execute(sa_delete(MeetingDocumentRecord).where(
                MeetingDocumentRecord.session_id == meeting_id))
            _bump("document", res.rowcount or 0)
        except Exception as e:  # noqa: BLE001
            rep.errors.append(f"meeting_documents:{type(e).__name__}")

        # 4) audio (S3 + batch + local)
        if include_audio:
            try:
                for fr in await inv.meeting_audio_files(db, meeting_id):
                    if fr.object_key:
                        await document_storage.delete_object(fr.object_key)
                        _bump("storage_object", 1)
                    fr.status = "deleted"
                    if not fr.deleted_at:
                        fr.deleted_at = datetime.utcnow()
                    _bump("audio", 1)
            except Exception as e:  # noqa: BLE001
                rep.errors.append(f"audio_files:{type(e).__name__}")
            try:
                res = await db.execute(sa_delete(BatchJob).where(BatchJob.meeting_id == meeting_id))
                _bump("audio", res.rowcount or 0)
            except Exception as e:  # noqa: BLE001
                rep.errors.append(f"batch_jobs:{type(e).__name__}")
            if m.audio_path and _is_under_allowed(m.audio_path):
                try:
                    real = os.path.realpath(m.audio_path)
                    if os.path.isfile(real):
                        os.remove(real)
                        _bump("audio", 1)
                    m.audio_path = None
                except Exception as e:  # noqa: BLE001
                    rep.errors.append(f"local_audio:{type(e).__name__}")

        # 4b) SavedTranscription — удалить локальные файлы (под allowed dir) ДО bulk-delete строк,
        # иначе экспортированные txt/json остаются на диске (Этап 25 review fix).
        try:
            saved = list((await db.execute(
                select(SavedTranscription).where(SavedTranscription.session_id == meeting_id))).scalars().all())
            for st in saved:
                if st.file_path and _is_under_allowed(st.file_path):
                    real = os.path.realpath(st.file_path)
                    if os.path.isfile(real):
                        os.remove(real)
                        _bump("storage_object", 1)
        except Exception as e:  # noqa: BLE001
            rep.errors.append(f"saved_transcription_files:{type(e).__name__}")

        # 5) content-таблицы (bulk delete по fk)
        for category, model, fk in _CONTENT_TABLES:
            try:
                res = await db.execute(sa_delete(model).where(getattr(model, fk) == meeting_id))
                _bump(category, res.rowcount or 0)
            except Exception as e:  # noqa: BLE001
                rep.errors.append(f"{model.__tablename__}:{type(e).__name__}")

        # 6) meeting record: очистка текстовых колонок ИЛИ полное удаление
        try:
            had_snapshot = 1 if m.ai_settings_snapshot_json else 0
            if include_meeting_record:
                res = await db.execute(sa_delete(MeetingParticipant).where(
                    MeetingParticipant.meeting_id == meeting_id))
                _bump("participant", res.rowcount or 0)
                await db.delete(m)
                _bump("meeting", 1)
            else:
                for col in inv.MEETING_TEXT_COLUMNS:
                    setattr(m, col, None)
                _bump("meeting", 1)
            _bump("ai_settings_snapshot", had_snapshot)  # снапшот (+ hints) вычищен/удалён
        except Exception as e:  # noqa: BLE001
            rep.errors.append(f"meeting_session:{type(e).__name__}")

        await db.commit()
        rep.executed = True
        rep.deleted_counts = counts
        rep.partial_delete = bool(rep.errors)
        log_privacy_event(logger, "privacy_delete_executed", meeting_id=meeting_id,
                          user_id=getattr(user, "id", None), counts=counts,
                          warnings=rep.errors)
        return rep
