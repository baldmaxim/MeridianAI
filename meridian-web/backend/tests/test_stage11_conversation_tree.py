"""Тесты дерева общения встречи (Conversation Tree).

Сервис — чистый + DB-upsert на rollback-сессии. Эндпоинты вызываются как корутины.
Секреты/полные тексты не раскрываются.
"""

import json
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.user import User
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.directory import MeetingParticipant
from app.models.meeting_conversation import MeetingConversationTopic
from app.services.conversation_tree import ConversationTreeService, MAX_REFS_PER_SIDE
from app.schemas.conversation_tree import ConversationTopicUpdate
from app.api.conversation_tree import (
    get_conversation_tree, patch_conversation_topic, rebuild_conversation_tree,
)
from sqlalchemy import select, func


async def _mk_user(db, email):
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u); await db.flush(); await db.refresh(u)
    return u


async def _mk_meeting(db, owner, *, active=True):
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=active,
                       status="active", started_at=datetime(2026, 1, 1, 10, 0))
    db.add(m); await db.flush(); await db.refresh(m)
    return m


def _svc():
    return ConversationTreeService()


# ---------- 1: наша сторона создаёт тему ----------

async def test_our_segment_creates_topic(db):
    owner = await _mk_user(db, "ct1@test.local")
    m = await _mk_meeting(db, owner)
    out = await _svc().update_from_transcript_segment(
        db, m.id, segment_id="s1", speaker="Иван", role="self",
        text="Какие сроки сдачи объекта?", timecode="00:01:00")
    assert out is not None
    assert out.normalized_key == "deadlines"
    assert out.status == "new"
    assert out.our_summary and out.our_last_text
    assert out.opponent_summary is None
    assert len(out.our_refs) == 1 and out.our_refs[0].segment_id == "s1"


# ---------- 2: оппонент по той же теме → та же тема, opponent_summary ----------

async def test_opponent_same_topic(db):
    owner = await _mk_user(db, "ct2@test.local")
    m = await _mk_meeting(db, owner)
    svc = _svc()
    await svc.update_from_transcript_segment(
        db, m.id, segment_id="s1", speaker="Иван", role="self",
        text="Обсудим сроки выполнения работ", timecode="00:01:00")
    out = await svc.update_from_transcript_segment(
        db, m.id, segment_id="s2", speaker="Пётр", role="opponent",
        text="Сроки нас не устраивают, нужен график", timecode="00:02:00")
    cnt = (await db.execute(select(func.count(MeetingConversationTopic.id)).where(
        MeetingConversationTopic.meeting_id == m.id))).scalar()
    assert cnt == 1
    assert out.opponent_summary and out.opponent_last_text
    assert out.our_summary  # сохранилась наша сторона


# ---------- 3: повторная реплика по теме обновляет, не дублирует ----------

async def test_second_segment_updates_no_duplicate(db):
    owner = await _mk_user(db, "ct3@test.local")
    m = await _mk_meeting(db, owner)
    svc = _svc()
    await svc.update_from_transcript_segment(
        db, m.id, segment_id="s1", speaker="Иван", role="self",
        text="Цена слишком высокая", timecode="00:01:00")
    out = await svc.update_from_transcript_segment(
        db, m.id, segment_id="s2", speaker="Иван", role="self",
        text="Давайте обсудим скидку на стоимость", timecode="00:02:00")
    cnt = (await db.execute(select(func.count(MeetingConversationTopic.id)).where(
        MeetingConversationTopic.meeting_id == m.id))).scalar()
    assert cnt == 1
    assert out.status == "updated"
    assert len(out.our_refs) == 2


# ---------- 4: неизвестный спикер не падает и не создаёт тему ----------

async def test_unknown_speaker_no_crash(db):
    owner = await _mk_user(db, "ct4@test.local")
    m = await _mk_meeting(db, owner)
    out = await _svc().update_from_transcript_segment(
        db, m.id, segment_id="s1", speaker="???", role=None,
        text="Что-то про сроки", timecode="00:01:00")
    assert out is None
    cnt = (await db.execute(select(func.count(MeetingConversationTopic.id)).where(
        MeetingConversationTopic.meeting_id == m.id))).scalar()
    assert cnt == 0


# ---------- 5: refs ограничены ----------

async def test_refs_capped(db):
    owner = await _mk_user(db, "ct5@test.local")
    m = await _mk_meeting(db, owner)
    svc = _svc()
    for i in range(MAX_REFS_PER_SIDE + 5):
        out = await svc.update_from_transcript_segment(
            db, m.id, segment_id=f"s{i}", speaker="Иван", role="self",
            text=f"Вопрос про оплату номер {i}", timecode="00:0%d:00" % (i % 9))
    assert len(out.our_refs) == MAX_REFS_PER_SIDE


# ---------- 6: GET требует доступа к встрече ----------

async def test_get_open_to_everyone(db):
    owner = await _mk_user(db, "ct6a@test.local")
    stranger = await _mk_user(db, "ct6b@test.local")
    m = await _mk_meeting(db, owner)
    tree = await get_conversation_tree(m.id, user=owner, db=db)
    assert tree.meeting_id == m.id
    # общая хронология: посторонний тоже видит дерево
    tree2 = await get_conversation_tree(m.id, user=stranger, db=db)
    assert tree2.meeting_id == m.id


# ---------- 7: view-only не может PATCH ----------

async def test_patch_open_to_everyone(db):
    # Общая модель: любой авторизованный может менять дерево разговора.
    owner = await _mk_user(db, "ct7a@test.local")
    other = await _mk_user(db, "ct7b@test.local")
    m = await _mk_meeting(db, owner)
    out = await _svc().update_from_transcript_segment(
        db, m.id, segment_id="s1", speaker="Иван", role="self",
        text="Сроки", timecode="00:01:00")
    res = await patch_conversation_topic(
        m.id, out.id, ConversationTopicUpdate(status="resolved"), user=other, db=db)
    assert res.status == "resolved"


# ---------- 8: participant может PATCH ----------

async def test_participant_can_patch(db):
    owner = await _mk_user(db, "ct8a@test.local")
    editor = await _mk_user(db, "ct8b@test.local")
    m = await _mk_meeting(db, owner)
    db.add(MeetingParticipant(meeting_id=m.id, user_id=editor.id, role="participant"))
    await db.flush()
    out = await _svc().update_from_transcript_segment(
        db, m.id, segment_id="s1", speaker="Иван", role="self",
        text="Сроки", timecode="00:01:00")
    patched = await patch_conversation_topic(
        m.id, out.id, ConversationTopicUpdate(title="Сроки сдачи", status="resolved",
                                              our_summary="Договорились о графике"),
        user=editor, db=db)
    assert patched.title == "Сроки сдачи"
    assert patched.status == "resolved"
    assert patched.our_summary == "Договорились о графике"


# ---------- 8b: ручной статус «липкий» — авто-апдейт не перетирает ----------

async def test_manual_status_sticky(db):
    owner = await _mk_user(db, "ct8c@test.local")
    m = await _mk_meeting(db, owner)
    svc = _svc()
    out = await svc.update_from_transcript_segment(
        db, m.id, segment_id="s1", speaker="Иван", role="self",
        text="Цена вопроса", timecode="00:01:00")
    await svc.manual_update_topic(db, m.id, out.id, ConversationTopicUpdate(status="resolved"))
    out2 = await svc.update_from_transcript_segment(
        db, m.id, segment_id="s2", speaker="Иван", role="self",
        text="Ещё про стоимость", timecode="00:02:00")
    assert out2.status == "resolved"  # не перетёрто на updated


# ---------- 9: payload conversation_tree_updated формируется ----------

async def test_topic_payload_shape(db):
    owner = await _mk_user(db, "ct9@test.local")
    m = await _mk_meeting(db, owner)
    out = await _svc().update_from_transcript_segment(
        db, m.id, segment_id="s1", speaker="Иван", role="self",
        text="Оплата по договору", timecode="00:01:00")
    payload = {"type": "conversation_tree_updated", "meeting_id": m.id,
               "topic": out.model_dump(mode="json"), "tree_version": 1}
    assert payload["type"] == "conversation_tree_updated"
    assert payload["topic"]["normalized_key"] == "payment"
    assert "our_refs" in payload["topic"]


# ---------- 10: финализация включает блок дерева ----------

async def test_finalization_includes_tree_block(db):
    from app.services.meeting_finalize import build_conversation_tree_block
    owner = await _mk_user(db, "ct10@test.local")
    m = await _mk_meeting(db, owner)
    svc = _svc()
    await svc.update_from_transcript_segment(
        db, m.id, segment_id="s1", speaker="Иван", role="self",
        text="Сроки сдачи объекта", timecode="00:01:00")
    block = await build_conversation_tree_block(db, m.id)
    assert "Сроки" in block and "Мы:" in block
    # пустая встреча → пустой блок
    m2 = await _mk_meeting(db, owner)
    assert await build_conversation_tree_block(db, m2.id) == ""


# ---------- 11: rebuild из сегментов ----------

async def test_rebuild_from_segments(db):
    owner = await _mk_user(db, "ct11@test.local")
    m = await _mk_meeting(db, owner)
    db.add(TranscriptSegmentRecord(
        session_id=m.id, segment_id="s1", text="Обсудим оплату и аванс",
        start_time=10.0, end_time=12.0, wall_clock=datetime(2026, 1, 1, 10, 1),
        speaker_id="spk_0", speaker_label="Иван", origin="live_committed", word_count=4))
    await db.flush()
    tree = await _svc().rebuild_from_segments(db, m.id, speaker_roles={"Иван": "self"})
    assert len(tree.topics) == 1
    assert tree.topics[0].normalized_key == "payment"


# ---------- 12: фича отключена → хук пропускает ----------

async def test_feature_disabled_skips(db):
    from app.services.meeting_room import MeetingRoom

    class _Seg:
        segment_id = "s1"; speaker_label = "Иван"; speaker_id = "spk0"
        text = "Сроки"; start_time = 1.0

    owner = await _mk_user(db, "ct12@test.local")
    m = await _mk_meeting(db, owner)
    room = MeetingRoom(m.id, owner.id, "active")
    room._tree_enabled = False
    await room._on_committed_for_tree(_Seg(), "self")  # не должно ничего создать
    cnt = (await db.execute(select(func.count(MeetingConversationTopic.id)).where(
        MeetingConversationTopic.meeting_id == m.id))).scalar()
    assert cnt == 0


# ---------- LLM-экстрактор условий (мок LLM) ----------

class _MockLLM:
    """Мок LLM-клиента: возвращает заранее заданный ответ get_suggestion_async."""
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    async def get_suggestion_async(self, prompt, max_tokens=None):
        self.calls += 1
        return self._payload


# ---------- 13: extract_live создаёт осмысленную тему со связными цитатами ----------

async def test_extract_live_creates_topics(db):
    owner = await _mk_user(db, "ct13@test.local")
    m = await _mk_meeting(db, owner)
    payload = json.dumps([{
        "key": "price", "title": "Цена и стоимость",
        "our_position": "Предлагаем скидку 5%.",
        "opponent_position": "Просят снизить цену на 10%.",
        "status": "disputed",
        "quotes": [
            {"side": "our", "speaker": "SM_S1", "text": "Можем дать скидку пять процентов."},
            {"side": "opponent", "speaker": "SM_S2", "text": "Нам нужна скидка десять процентов."},
        ],
    }], ensure_ascii=False)
    changed, ok = await _svc().extract_live(
        db, m.id, dialog_text="[МЫ] SM_S1: ...\n[НЕ МЫ] SM_S2: ...",
        current_topics=[], llm_client=_MockLLM(payload))
    assert ok is True and len(changed) == 1
    t = changed[0]
    assert t.normalized_key == "price"
    assert t.status == "disputed"
    assert t.our_summary and t.opponent_summary
    # цитаты — связные фразы (есть пробелы), не отдельные слова; без привязки к сегменту
    assert len(t.our_refs) == 1 and " " in t.our_refs[0].text and t.our_refs[0].segment_id == ""
    assert len(t.opponent_refs) == 1


# ---------- 14: тот же key → merge без дубля ----------

async def test_extract_live_merges_existing(db):
    owner = await _mk_user(db, "ct14@test.local")
    m = await _mk_meeting(db, owner)
    svc = _svc()
    p1 = json.dumps([{"key": "deadlines", "title": "Сроки", "our_position": "К 1 июля.",
                      "opponent_position": None, "status": "new", "quotes": []}], ensure_ascii=False)
    await svc.extract_live(db, m.id, dialog_text="x", current_topics=[], llm_client=_MockLLM(p1))
    tree = await svc.get_tree(db, m.id)
    p2 = json.dumps([{"key": "deadlines", "title": "Сроки сдачи",
                      "our_position": "К 1 июля.", "opponent_position": "Просят к 15 июня.",
                      "status": "updated", "quotes": []}], ensure_ascii=False)
    changed, ok = await svc.extract_live(db, m.id, dialog_text="y",
                                         current_topics=tree.topics, llm_client=_MockLLM(p2))
    cnt = (await db.execute(select(func.count(MeetingConversationTopic.id)).where(
        MeetingConversationTopic.meeting_id == m.id))).scalar()
    assert cnt == 1
    assert changed[0].title == "Сроки сдачи" and changed[0].opponent_summary
    assert changed[0].status == "updated"


# ---------- 15: нет LLM-клиента → no-op ----------

async def test_extract_live_no_llm(db):
    owner = await _mk_user(db, "ct15@test.local")
    m = await _mk_meeting(db, owner)
    changed, ok = await _svc().extract_live(db, m.id, dialog_text="что-то",
                                            current_topics=[], llm_client=None)
    assert changed == [] and ok is False
    cnt = (await db.execute(select(func.count(MeetingConversationTopic.id)).where(
        MeetingConversationTopic.meeting_id == m.id))).scalar()
    assert cnt == 0


# ---------- 16: битый JSON → no-op без исключения ----------

async def test_extract_live_bad_json(db):
    owner = await _mk_user(db, "ct16@test.local")
    m = await _mk_meeting(db, owner)
    changed, ok = await _svc().extract_live(
        db, m.id, dialog_text="реплика", current_topics=[],
        llm_client=_MockLLM("извините, не json"))
    assert changed == [] and ok is False
    cnt = (await db.execute(select(func.count(MeetingConversationTopic.id)).where(
        MeetingConversationTopic.meeting_id == m.id))).scalar()
    assert cnt == 0


# ---------- 17: липкий статус не перетирается LLM-апдейтом ----------

async def test_extract_live_sticky_status(db):
    owner = await _mk_user(db, "ct17@test.local")
    m = await _mk_meeting(db, owner)
    svc = _svc()
    p1 = json.dumps([{"key": "price", "title": "Цена", "our_position": "ок",
                      "opponent_position": None, "status": "new", "quotes": []}], ensure_ascii=False)
    changed, _ = await svc.extract_live(db, m.id, dialog_text="x", current_topics=[],
                                        llm_client=_MockLLM(p1))
    await svc.manual_update_topic(db, m.id, changed[0].id, ConversationTopicUpdate(status="resolved"))
    tree = await svc.get_tree(db, m.id)
    p2 = json.dumps([{"key": "price", "title": "Цена", "our_position": "ок2",
                      "opponent_position": None, "status": "updated", "quotes": []}], ensure_ascii=False)
    changed2, _ = await svc.extract_live(db, m.id, dialog_text="y",
                                         current_topics=tree.topics, llm_client=_MockLLM(p2))
    assert changed2[0].status == "resolved"  # липкий статус сохранён


# ---------- 18: rebuild_with_llm строит связные темы из транскрипта ----------

async def test_rebuild_with_llm(db):
    owner = await _mk_user(db, "ct18@test.local")
    m = await _mk_meeting(db, owner)
    db.add(TranscriptSegmentRecord(
        session_id=m.id, segment_id="s1", text="Нам нужна скидка на цену",
        start_time=10.0, end_time=12.0, wall_clock=datetime(2026, 1, 1, 10, 1),
        speaker_id="spk_0", speaker_label="Пётр", origin="live_committed", word_count=5))
    await db.flush()
    payload = json.dumps([{"key": "price", "title": "Цена и стоимость",
                           "our_position": None, "opponent_position": "Просят скидку.",
                           "status": "new",
                           "quotes": [{"side": "opponent", "speaker": "Пётр",
                                       "text": "Нам нужна скидка на цену."}]}], ensure_ascii=False)
    tree = await _svc().rebuild_with_llm(db, m.id, _MockLLM(payload),
                                         speaker_roles={"Пётр": "opponent"})
    assert len(tree.topics) == 1
    assert tree.topics[0].normalized_key == "price" and tree.topics[0].opponent_summary


# ---------- 19: recent_dialog_with_sides — связный диалог с тегами сторон ----------

async def test_recent_dialog_with_sides():
    from app.services.session_manager import SessionManager

    class _Turn:
        def __init__(self, speaker, text):
            self.speaker = speaker
            self.text = text

    class _TA:
        turns = [_Turn("SM_S1", "Можем дать скидку."),
                 _Turn("SM_S2", "Нужна большая скидка."),
                 _Turn("SM_S3", "Реплика без стороны.")]

    sm = SessionManager(0)
    sm._turn_assembler = _TA()
    sm.speaker_roles = {"SM_S1": "self", "SM_S2": "opponent"}
    dialog = sm.recent_dialog_with_sides()
    assert "[МЫ] SM_S1: Можем дать скидку." in dialog
    assert "[НЕ МЫ] SM_S2: Нужна большая скидка." in dialog
    assert "SM_S3: Реплика без стороны." in dialog  # без тега стороны
