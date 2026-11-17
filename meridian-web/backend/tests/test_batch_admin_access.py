# -*- coding: utf-8 -*-
"""Доступ администратора к записям «Расшифровки» всех пользователей.

Чтение (список scope=all, карточка) — admin видит чужое; изменение (удаление) — только владелец.
Эндпоинты вызываются как корутины, db/user передаются явно.
"""

import pytest
from fastapi import HTTPException

from app.api.batch import delete_batch_job, get_batch_job, list_batch_jobs
from app.models.batch_job import BatchJob
from app.models.user import User


async def _mk_user(db, email: str, role: str = "user", display_name: str | None = None) -> User:
    u = User(email=email, password_hash="x", role=role, is_active=True, display_name=display_name)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _mk_job(db, user: User, name: str) -> BatchJob:
    job = BatchJob(user_id=user.id, status="done", original_filename=name, file_path=f"batch/{name}")
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def test_admin_scope_all_sees_foreign_jobs_with_owner(db):
    admin = await _mk_user(db, "adm-ba@test.local", role="admin")
    owner = await _mk_user(db, "own-ba@test.local", display_name="Owner Name")
    mine = await _mk_job(db, admin, "mine.m4a")
    foreign = await _mk_job(db, owner, "foreign.m4a")

    only_mine = await list_batch_jobs(scope="mine", user=admin, db=db)
    assert {j.id for j in only_mine} == {mine.id}

    everything = await list_batch_jobs(scope="all", user=admin, db=db)
    by_id = {j.id: j for j in everything}
    assert {mine.id, foreign.id} <= set(by_id)
    assert by_id[foreign.id].owner_id == owner.id
    assert by_id[foreign.id].owner_name == "Owner Name"
    assert by_id[mine.id].owner_name == admin.email


async def test_user_scope_all_is_ignored(db):
    user = await _mk_user(db, "usr-ba@test.local")
    other = await _mk_user(db, "oth-ba@test.local")
    mine = await _mk_job(db, user, "mine.m4a")
    await _mk_job(db, other, "other.m4a")

    jobs = await list_batch_jobs(scope="all", user=user, db=db)
    assert {j.id for j in jobs} == {mine.id}


async def test_user_gets_404_on_foreign_job(db):
    user = await _mk_user(db, "usr2-ba@test.local")
    other = await _mk_user(db, "oth2-ba@test.local")
    foreign = await _mk_job(db, other, "other.m4a")

    with pytest.raises(HTTPException) as e:
        await get_batch_job(job_id=foreign.id, user=user, db=db)
    assert e.value.status_code == 404


async def test_admin_reads_foreign_job_but_cannot_delete(db):
    admin = await _mk_user(db, "adm2-ba@test.local", role="admin")
    owner = await _mk_user(db, "own2-ba@test.local")
    foreign = await _mk_job(db, owner, "other.m4a")

    detail = await get_batch_job(job_id=foreign.id, user=admin, db=db)
    assert detail.id == foreign.id and detail.owner_id == owner.id

    with pytest.raises(HTTPException) as e:
        await delete_batch_job(job_id=foreign.id, user=admin, db=db)
    assert e.value.status_code == 404
