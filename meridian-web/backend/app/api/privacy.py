"""Privacy / retention / delete / export API (Этап 25). Mounted at /api/meetings.

Safe-by-default: inventory/export/delete-plan доступны при PRIVACY_CONTROLS_ENABLED; hard delete
требует PRIVACY_HARD_DELETE_ENABLED + (опц.) confirmation_token из dry-run плана и права
creator/admin. Логи — только counts (без raw content).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..config import get_settings
from ..models.user import User
from ..models.meeting import MeetingSession
from ..auth.dependencies import get_current_user
from ..services.access import user_can_access_meeting
from ..services.privacy_data_inventory import PrivacyDataInventoryService, PrivacyInventoryReport
from ..services.privacy_export_service import PrivacyExportService, PrivacyExportManifest
from ..services.privacy_delete_service import (
    PrivacyDeleteService, PrivacyDeletePlan, PrivacyDeleteExecutionReport,
)
from ..core.privacy.privacy_audit import log_privacy_event

logger = logging.getLogger("meridian.privacy")

router = APIRouter()

_inventory = PrivacyDataInventoryService()
_export = PrivacyExportService()
_delete = PrivacyDeleteService()


class DeletePlanRequest(BaseModel):
    include_documents: bool = True
    include_audio: bool = True
    include_meeting_record: bool = False


class DeleteDataRequest(BaseModel):
    confirmation_token: str | None = None
    include_documents: bool = True
    include_audio: bool = True
    include_meeting_record: bool = False


def _require_controls():
    if not get_settings().privacy_controls_enabled:
        raise HTTPException(403, "Privacy-контролы отключены")


async def _require_meeting_access(db: AsyncSession, user: User, meeting_id: int):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(404, "Встреча не найдена")


async def _require_hard_delete_permission(db: AsyncSession, user: User, meeting_id: int) -> MeetingSession:
    m = await db.get(MeetingSession, meeting_id)
    if m is None:
        raise HTTPException(404, "Встреча не найдена")
    is_owner = m.created_by_user_id == user.id or m.user_id == user.id
    if not (is_owner or user.role == "admin"):
        raise HTTPException(403, "Удаление данных доступно только создателю встречи или админу")
    return m


@router.get("/{meeting_id}/privacy/inventory", response_model=PrivacyInventoryReport)
async def get_privacy_inventory(meeting_id: int, user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    _require_controls()
    await _require_meeting_access(db, user, meeting_id)
    report = await _inventory.build_meeting_inventory(db, meeting_id, user)
    log_privacy_event(logger, "privacy_inventory_viewed", meeting_id=meeting_id, user_id=user.id,
                      counts=report.totals, warnings=report.warnings)
    return report


@router.get("/{meeting_id}/privacy/export", response_model=PrivacyExportManifest)
async def get_privacy_export(meeting_id: int,
                             include_documents: bool = Query(False),
                             include_audio: bool = Query(False),
                             format: str = Query("json"),
                             user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    _require_controls()
    if not get_settings().privacy_export_enabled:
        raise HTTPException(403, "Экспорт отключён")
    if format != "json":
        raise HTTPException(400, "В v1 поддерживается только format=json")
    await _require_meeting_access(db, user, meeting_id)
    return await _export.build_export_manifest(
        db, meeting_id, user, include_documents=include_documents, include_audio=include_audio)


@router.post("/{meeting_id}/privacy/delete-plan", response_model=PrivacyDeletePlan)
async def post_privacy_delete_plan(meeting_id: int, body: DeletePlanRequest,
                                   user: User = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)):
    _require_controls()
    # dry-run план — только создатель/админ (готовит confirmation_token к удалению)
    await _require_hard_delete_permission(db, user, meeting_id)
    return await _delete.build_delete_plan(
        db, meeting_id, user, include_documents=body.include_documents,
        include_audio=body.include_audio, include_meeting_record=body.include_meeting_record)


@router.delete("/{meeting_id}/privacy/data", response_model=PrivacyDeleteExecutionReport)
async def delete_privacy_data(meeting_id: int, body: DeleteDataRequest,
                              user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    _require_controls()
    if not get_settings().privacy_hard_delete_enabled:
        raise HTTPException(403, "Жёсткое удаление отключено (PRIVACY_HARD_DELETE_ENABLED=false)")
    await _require_hard_delete_permission(db, user, meeting_id)
    rep = await _delete.execute_delete_plan(
        db, meeting_id, user, dry_run=False, confirmation_token=body.confirmation_token,
        include_documents=body.include_documents, include_audio=body.include_audio,
        include_meeting_record=body.include_meeting_record)
    if not rep.executed and rep.blockers:
        # безопасная 4xx без раскрытия внутренних деталей
        raise HTTPException(409, f"Удаление не выполнено: {', '.join(rep.blockers)}")
    return rep
