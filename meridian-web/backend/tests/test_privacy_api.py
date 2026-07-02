"""Этап 25: privacy API — inventory/export/delete-plan + гейты (controls/hard-delete/permission)."""

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.api import privacy as papi
from app.api.privacy import DeletePlanRequest, DeleteDataRequest
from tests.privacy_test_utils import (  # noqa: F401
    commit_db, mk_user, mk_meeting, add_transcript,
)


async def test_api_inventory(commit_db):
    owner = await mk_user(commit_db, "api1@t.local")
    m = await mk_meeting(commit_db, owner)
    await add_transcript(commit_db, m)
    await commit_db.commit()
    rep = await papi.get_privacy_inventory(m.id, user=owner, db=commit_db)
    assert rep.meeting_id == m.id and rep.totals["transcript"] >= 1


async def test_api_export(commit_db):
    owner = await mk_user(commit_db, "api2@t.local")
    m = await mk_meeting(commit_db, owner)
    await add_transcript(commit_db, m)
    await commit_db.commit()
    man = await papi.get_privacy_export(m.id, include_documents=False, include_audio=False,
                                        format="json", user=owner, db=commit_db)
    assert "transcript" in man.sections


async def test_api_delete_plan_creator_ok(commit_db):
    owner = await mk_user(commit_db, "api3@t.local")
    m = await mk_meeting(commit_db, owner)
    await commit_db.commit()
    plan = await papi.post_privacy_delete_plan(m.id, DeletePlanRequest(), user=owner, db=commit_db)
    assert plan.dry_run is True


async def test_api_delete_plan_stranger_forbidden(commit_db):
    owner = await mk_user(commit_db, "api4-o@t.local")
    stranger = await mk_user(commit_db, "api4-s@t.local")
    m = await mk_meeting(commit_db, owner)
    await commit_db.commit()
    with pytest.raises(HTTPException) as e:
        await papi.post_privacy_delete_plan(m.id, DeletePlanRequest(), user=stranger, db=commit_db)
    assert e.value.status_code == 403


async def test_api_delete_plan_admin_ok(commit_db):
    owner = await mk_user(commit_db, "api5-o@t.local")
    admin = await mk_user(commit_db, "api5-a@t.local", role="admin")
    m = await mk_meeting(commit_db, owner)
    await commit_db.commit()
    plan = await papi.post_privacy_delete_plan(m.id, DeletePlanRequest(), user=admin, db=commit_db)
    assert plan.dry_run is True


async def test_api_delete_disabled_returns_403(commit_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "privacy_hard_delete_enabled", False)
    owner = await mk_user(commit_db, "api6@t.local")
    m = await mk_meeting(commit_db, owner)
    await commit_db.commit()
    with pytest.raises(HTTPException) as e:
        await papi.delete_privacy_data(m.id, DeleteDataRequest(confirmation_token=None),
                                       user=owner, db=commit_db)
    assert e.value.status_code == 403


async def test_api_controls_disabled_returns_403(commit_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "privacy_controls_enabled", False)
    owner = await mk_user(commit_db, "api7@t.local")
    m = await mk_meeting(commit_db, owner)
    await commit_db.commit()
    with pytest.raises(HTTPException) as e:
        await papi.get_privacy_inventory(m.id, user=owner, db=commit_db)
    assert e.value.status_code == 403
