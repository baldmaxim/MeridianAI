# -*- coding: utf-8 -*-
"""Ручки агента распознавания сканов.

К агентским ручкам ходит не браузер, а программа на компьютере пользователя, где в LM Studio
работает chandra-ocr-2. Отсюда отличия: вход по токену в заголовке вместо сессии и ответы,
рассчитанные на цикл, а не на человека. Направление обращено намеренно: сервер не достучится
до домашней машины за NAT, поэтому агент ходит сюда сам, и на компьютере не открыт ни один
входящий порт.

Админские ручки (завести / отозвать агента, состояние очереди) — в том же модуле, чтобы весь
контракт агента читался в одном месте.
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_admin
from ..config import get_settings
from ..database import get_db
from ..models.ocr import OcrAgent
from ..models.user import User
from ..services import s3
from ..services.ocr_queue import (
    OcrQueueError,
    authenticate_agent,
    claim_task,
    complete_task,
    enroll_agent,
    fail_task,
    note_agent,
    queue_status,
    revoke_agent,
    submit_page,
)

logger = logging.getLogger("meridian.ocr_agent")

agent_router = APIRouter()
admin_router = APIRouter()


async def current_agent(
    db: AsyncSession = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
) -> OcrAgent:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    agent = await authenticate_agent(db, token)
    if agent is None:
        # В лог — факт, но не токен.
        logger.warning("неопознанный OCR-агент постучался в очередь")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Токен агента не принят")
    return agent


Agent = Annotated[OcrAgent, Depends(current_agent)]


def _queue_error(e: OcrQueueError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


# ── агент ──────────────────────────────────────────────────────────────────


class AgentHello(BaseModel):
    model: str | None = Field(default=None, max_length=200)
    agent_version: str | None = Field(default=None, max_length=40)


@agent_router.post("/heartbeat")
async def heartbeat(payload: AgentHello, agent: Agent, db: AsyncSession = Depends(get_db)):
    """Отметиться. Отдельно от claim — чтобы админка видела, что компьютер на связи."""
    note_agent(agent, payload.model, payload.agent_version)
    await db.commit()
    return {"ok": True, "agent": agent.name}


@agent_router.post("/claim")
async def claim(payload: AgentHello, agent: Agent, db: AsyncSession = Depends(get_db)):
    """Взять одну задачу в аренду. {"task": null} — очередь пуста."""
    note_agent(agent, payload.model, payload.agent_version)
    ttl = get_settings().ocr_agent_pdf_url_ttl_seconds
    task = await claim_task(db, agent, pdf_url_for=lambda key: s3.presign_get(key, ttl=ttl))
    await db.commit()
    return {"task": task}


class PageIn(BaseModel):
    page_number: int = Field(ge=1)
    pages_total: int = Field(ge=1)
    text: str = ""
    model: str | None = Field(default=None, max_length=200)


@agent_router.post("/tasks/{task_id}/pages")
async def put_page(task_id: int, payload: PageIn, agent: Agent, db: AsyncSession = Depends(get_db)):
    """Сдать одну распознанную страницу. Продлевает аренду."""
    try:
        done = await submit_page(db, agent, task_id, page_number=payload.page_number,
                                 pages_total=payload.pages_total, text=payload.text,
                                 model=payload.model)
    except OcrQueueError as e:
        raise _queue_error(e)
    await db.commit()
    return {"ok": True, "pages_done": done}


@agent_router.post("/tasks/{task_id}/complete")
async def complete(task_id: int, agent: Agent, db: AsyncSession = Depends(get_db)):
    try:
        await complete_task(db, agent, task_id)
    except OcrQueueError as e:
        raise _queue_error(e)
    await db.commit()
    return {"ok": True}


class FailIn(BaseModel):
    error: str = Field(default="", max_length=2000)


@agent_router.post("/tasks/{task_id}/fail")
async def fail(task_id: int, payload: FailIn, agent: Agent, db: AsyncSession = Depends(get_db)):
    try:
        await fail_task(db, agent, task_id, payload.error)
    except OcrQueueError as e:
        raise _queue_error(e)
    await db.commit()
    return {"ok": True}


# ── админка ────────────────────────────────────────────────────────────────


class EnrollIn(BaseModel):
    name: str = Field(default="Компьютер с LM Studio", max_length=120)


class AgentOut(BaseModel):
    id: int
    name: str
    model: str | None = None
    agent_version: str | None = None
    created_at: datetime | None = None
    last_seen_at: datetime | None = None
    online: bool = False


@admin_router.get("")
async def status_view(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Агенты и очередь: сколько сканов ждёт, сколько в работе, на связи ли компьютер."""
    return await queue_status(db)


@admin_router.post("", status_code=status.HTTP_201_CREATED)
async def enroll(payload: EnrollIn, admin: User = Depends(require_admin),
                 db: AsyncSession = Depends(get_db)):
    """Подключить компьютер. Токен показывается ровно один раз: в базе только его хэш."""
    agent, token = await enroll_agent(db, payload.name, admin.id)
    await db.commit()
    return {"agent": AgentOut(id=agent.id, name=agent.name, created_at=agent.created_at),
            "token": token}


@admin_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke(agent_id: int, admin: User = Depends(require_admin),
                 db: AsyncSession = Depends(get_db)):
    """Отозвать агента. Его арендованные задачи сразу возвращаются в очередь."""
    if not await revoke_agent(db, agent_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Агент не найден или уже отозван")
    await db.commit()
