"""ConversationTreeService — дерево общения встречи.

Детерминированный слой: по committed-сегменту определяет сторону (наша/оппонент)
и тему по ключевым словам, делает upsert темы (без дублей). LLM-уточнение — по запросу.

Безопасность: тексты усечены, refs ограничены, в логи не пишем полный текст реплик.
"""

import json
import logging
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.meeting_conversation import MeetingConversationTopic, STICKY_STATUSES
from ..models.meeting import TranscriptSegmentRecord
from ..schemas.conversation_tree import (
    ConversationTopicOut, ConversationTopicRef, ConversationTreeOut, ConversationTopicUpdate,
)

logger = logging.getLogger("meridian.conversation_tree")

MAX_REFS_PER_SIDE = 10
MAX_SUMMARY_CHARS = 280
MAX_TEXT_CHARS = 280

# Ordered keyword buckets (RU, строительная сфера). Первое совпадение выигрывает.
# (normalized_key, человекочитаемый title, [подстроки-ключи в lower-case])
TOPIC_BUCKETS: list[tuple[str, str, tuple[str, ...]]] = [
    ("price", "Цена и стоимость", ("цена", "цены", "стоим", "скидк", "дешев", "дорог", "прайс", "расцен", "бюджет")),
    ("deadlines", "Сроки", ("срок", "график", "дедлайн", "к какому числ", "когда сдад", "когда будет", "успе", "график работ")),
    ("payment", "Оплата", ("оплат", "платеж", "платёж", "предоплат", "аванс", "рассрочк", "транш", "счёт на", "счет на")),
    ("contract", "Договор и допсоглашения", ("договор", "контракт", "доп.соглаш", "допсоглаш", "соглашен", " дс ", "доп соглаш")),
    ("documents", "Документы", ("документ", " акт", "акт ", "справк", "накладн", "счёт-фактур", "счет-фактур", "смет")),
    ("warranty", "Гарантия", ("гаранти",)),
    ("quality", "Качество", ("качеств", "брак", "дефект", "недостат", "переделк")),
    ("responsibility", "Ответственность и санкции", ("ответствен", "штраф", "неустойк", "пеня", "пени", "санкци")),
    ("volumes", "Объёмы работ", ("объём", "объем", "количеств", "метраж", "кубатур", "тонн", "м2", "м3")),
    ("extra_work", "Дополнительные работы", ("допработ", "доп. работ", "доп работ", "дополнительн работ", "вне сметы")),
    ("supply", "Поставка и материалы", ("поставк", "достав", "привоз", "логистик", "отгрузк", "материал")),
]
OTHER_KEY = "other"
OTHER_TITLE = "Прочее"


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _roll_summary(existing: str | None, new_text: str) -> str:
    """Скользящее краткое содержание стороны: добавляем последнюю реплику, держим ≤ лимита."""
    new_text = (new_text or "").strip()
    if not existing:
        return _truncate(new_text, MAX_SUMMARY_CHARS)
    combined = f"{existing} · {new_text}"
    if len(combined) <= MAX_SUMMARY_CHARS:
        return combined
    # держим хвост (самое свежее), не обрезая по середине слова грубо
    tail = combined[-MAX_SUMMARY_CHARS:]
    return "…" + tail[tail.find(" ") + 1:] if " " in tail else tail


class ConversationTreeService:
    # ---------- детерминированный слой ----------

    @staticmethod
    def classify_segment_topic(text: str) -> tuple[str, str]:
        low = (text or "").lower()
        for key, title, kws in TOPIC_BUCKETS:
            if any(kw in low for kw in kws):
                return key, title
        return OTHER_KEY, OTHER_TITLE

    @staticmethod
    def side_from_role(role: str | None) -> str | None:
        """our | opponent | None (skip)."""
        if role in ("self", "ally"):
            return "our"
        if role == "opponent":
            return "opponent"
        return None

    # ---------- сериализация ----------

    @staticmethod
    def _parse_refs(raw: str | None) -> list[ConversationTopicRef]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        out = []
        for r in data if isinstance(data, list) else []:
            try:
                out.append(ConversationTopicRef(
                    segment_id=str(r.get("segment_id", "")),
                    speaker=str(r.get("speaker", "")),
                    timecode=str(r.get("timecode", "")),
                    text=str(r.get("text", "")),
                ))
            except Exception:
                continue
        return out

    @classmethod
    def topic_to_out(cls, t: MeetingConversationTopic) -> ConversationTopicOut:
        return ConversationTopicOut(
            id=t.id,
            meeting_id=t.meeting_id,
            title=t.title,
            normalized_key=t.normalized_key,
            status=t.status,
            our_summary=t.our_summary,
            opponent_summary=t.opponent_summary,
            our_last_text=t.our_last_text,
            opponent_last_text=t.opponent_last_text,
            our_refs=cls._parse_refs(t.our_refs_json),
            opponent_refs=cls._parse_refs(t.opponent_refs_json),
            last_updated_at=t.last_updated_at,
            created_at=t.created_at,
        )

    # ---------- upsert ----------

    async def upsert_topic(
        self, db: AsyncSession, meeting_id: int, *, side: str, normalized_key: str,
        title: str, segment_id: str, speaker: str, text: str, timecode: str,
    ) -> MeetingConversationTopic:
        topic = (await db.execute(
            select(MeetingConversationTopic).where(
                MeetingConversationTopic.meeting_id == meeting_id,
                MeetingConversationTopic.normalized_key == normalized_key,
            )
        )).scalar_one_or_none()

        now = datetime.utcnow()
        clipped = _truncate(text, MAX_TEXT_CHARS)
        ref = {"segment_id": str(segment_id), "speaker": speaker,
               "timecode": timecode, "text": clipped}

        if topic is None:
            topic = MeetingConversationTopic(
                meeting_id=meeting_id, title=title, normalized_key=normalized_key,
                status="new", last_updated_at=now, created_at=now, updated_at=now,
            )
            db.add(topic)

        refs_attr = "our_refs_json" if side == "our" else "opponent_refs_json"
        refs = self._parse_refs(getattr(topic, refs_attr))
        refs_data = [r.model_dump() for r in refs]
        refs_data.append(ref)
        refs_data = refs_data[-MAX_REFS_PER_SIDE:]
        setattr(topic, refs_attr, json.dumps(refs_data, ensure_ascii=False))

        if side == "our":
            topic.our_summary = _roll_summary(topic.our_summary, text)
            topic.our_last_text = clipped
        else:
            topic.opponent_summary = _roll_summary(topic.opponent_summary, text)
            topic.opponent_last_text = clipped

        # статус: new при создании остаётся new; иначе updated (но не перетираем липкие ручные)
        if topic.id is not None and topic.status not in STICKY_STATUSES:
            topic.status = "updated"
        topic.last_updated_at = now
        await db.flush()
        return topic

    async def update_from_transcript_segment(
        self, db: AsyncSession, meeting_id: int, *, segment_id: str, speaker: str,
        role: str | None, text: str, timecode: str,
    ) -> ConversationTopicOut | None:
        """Главная точка входа из live-пайплайна. Возвращает обновлённую тему или None (skip)."""
        side = self.side_from_role(role)
        if side is None or not (text or "").strip():
            return None
        key, title = self.classify_segment_topic(text)
        topic = await self.upsert_topic(
            db, meeting_id, side=side, normalized_key=key, title=title,
            segment_id=segment_id, speaker=speaker, text=text, timecode=timecode,
        )
        return self.topic_to_out(topic)

    # ---------- чтение ----------

    async def get_tree(self, db: AsyncSession, meeting_id: int) -> ConversationTreeOut:
        rows = (await db.execute(
            select(MeetingConversationTopic)
            .where(MeetingConversationTopic.meeting_id == meeting_id)
            .order_by(MeetingConversationTopic.last_updated_at.asc())
        )).scalars().all()
        topics = [self.topic_to_out(t) for t in rows]
        version = sum(len(t.our_refs) + len(t.opponent_refs) for t in topics) + len(topics)
        return ConversationTreeOut(meeting_id=meeting_id, tree_version=version, topics=topics)

    # ---------- ручное редактирование ----------

    async def manual_update_topic(
        self, db: AsyncSession, meeting_id: int, topic_id: int, patch: ConversationTopicUpdate,
    ) -> ConversationTopicOut | None:
        topic = (await db.execute(
            select(MeetingConversationTopic).where(
                MeetingConversationTopic.id == topic_id,
                MeetingConversationTopic.meeting_id == meeting_id,
            )
        )).scalar_one_or_none()
        if topic is None:
            return None
        data = patch.model_dump(exclude_unset=True)
        if "title" in data and data["title"]:
            topic.title = data["title"]
        if "status" in data and data["status"]:
            topic.status = data["status"]
        if "our_summary" in data:
            topic.our_summary = _truncate(data["our_summary"] or "", 2000) or None
        if "opponent_summary" in data:
            topic.opponent_summary = _truncate(data["opponent_summary"] or "", 2000) or None
        topic.last_updated_at = datetime.utcnow()
        await db.flush()
        return self.topic_to_out(topic)

    async def merge_topics(
        self, db: AsyncSession, meeting_id: int, source_id: int, target_id: int,
    ) -> ConversationTopicOut | None:
        """Слить source в target (refs/summary), удалить source. Optional helper."""
        if source_id == target_id:
            return None
        src = (await db.execute(select(MeetingConversationTopic).where(
            MeetingConversationTopic.id == source_id,
            MeetingConversationTopic.meeting_id == meeting_id))).scalar_one_or_none()
        tgt = (await db.execute(select(MeetingConversationTopic).where(
            MeetingConversationTopic.id == target_id,
            MeetingConversationTopic.meeting_id == meeting_id))).scalar_one_or_none()
        if not src or not tgt:
            return None
        for side, attr in (("our", "our_refs_json"), ("opponent", "opponent_refs_json")):
            merged = self._parse_refs(getattr(tgt, attr)) + self._parse_refs(getattr(src, attr))
            merged_data = [r.model_dump() for r in merged][-MAX_REFS_PER_SIDE:]
            setattr(tgt, attr, json.dumps(merged_data, ensure_ascii=False) if merged_data else None)
        tgt.our_summary = tgt.our_summary or src.our_summary
        tgt.opponent_summary = tgt.opponent_summary or src.opponent_summary
        tgt.our_last_text = tgt.our_last_text or src.our_last_text
        tgt.opponent_last_text = tgt.opponent_last_text or src.opponent_last_text
        tgt.status = "updated" if tgt.status not in STICKY_STATUSES else tgt.status
        tgt.last_updated_at = datetime.utcnow()
        await db.delete(src)
        await db.flush()
        return self.topic_to_out(tgt)

    # ---------- пересборка из транскрипта ----------

    async def rebuild_from_segments(
        self, db: AsyncSession, meeting_id: int, speaker_roles: dict[str, str] | None = None,
    ) -> ConversationTreeOut:
        """Удалить дерево и пересобрать из persisted TranscriptSegmentRecord.

        Роли спикеров не персистятся — передаются явно (speaker_roles). Без ролей дерево пустое.
        """
        speaker_roles = speaker_roles or {}
        await db.execute(delete(MeetingConversationTopic).where(
            MeetingConversationTopic.meeting_id == meeting_id))
        await db.flush()
        segs = (await db.execute(
            select(TranscriptSegmentRecord)
            .where(TranscriptSegmentRecord.session_id == meeting_id)
            .order_by(TranscriptSegmentRecord.wall_clock.asc())
        )).scalars().all()
        for s in segs:
            speaker = s.speaker_label or s.speaker_id
            role = speaker_roles.get(speaker)
            tc = f"{int(s.start_time or 0)//60:02d}:{int(s.start_time or 0)%60:02d}"
            await self.update_from_transcript_segment(
                db, meeting_id, segment_id=s.segment_id, speaker=speaker,
                role=role, text=s.text, timecode=tc,
            )
        await db.flush()
        return await self.get_tree(db, meeting_id)

    # ---------- LLM-уточнение (по запросу) ----------

    async def refine_with_llm(self, db: AsyncSession, meeting_id: int, llm_client) -> ConversationTreeOut:
        """Переименовать темы и улучшить summary через LLM. Best-effort; ошибки не валят дерево."""
        tree = await self.get_tree(db, meeting_id)
        if not tree.topics or llm_client is None:
            return tree
        compact = [{
            "id": t.id, "title": t.title,
            "our": _truncate(t.our_summary or "", 200),
            "opponent": _truncate(t.opponent_summary or "", 200),
        } for t in tree.topics]
        prompt = (
            "Ниже темы переговоров с краткими позициями сторон. Улучши читаемость: уточни заголовки "
            "и при необходимости перепиши summary каждой стороны кратко и по-деловому. "
            "Не выдумывай фактов. Верни ТОЛЬКО JSON-массив объектов "
            '{"id": <int>, "title": "...", "our_summary": "...", "opponent_summary": "..."}.\n\n'
            + json.dumps(compact, ensure_ascii=False)
        )
        try:
            raw = await llm_client.get_suggestion_async(prompt)
        except Exception as e:
            logger.warning("refine: meeting %s LLM error: %s", meeting_id, str(e)[:120])
            return tree
        items = self._parse_json_array(raw)
        if not items:
            return tree
        by_id = {t.id: t for t in tree.topics}
        for it in items:
            try:
                tid = int(it.get("id"))
            except (TypeError, ValueError):
                continue
            if tid not in by_id:
                continue
            topic = (await db.execute(select(MeetingConversationTopic).where(
                MeetingConversationTopic.id == tid,
                MeetingConversationTopic.meeting_id == meeting_id))).scalar_one_or_none()
            if not topic:
                continue
            if it.get("title"):
                topic.title = _truncate(str(it["title"]), 255)
            if it.get("our_summary"):
                topic.our_summary = _truncate(str(it["our_summary"]), MAX_SUMMARY_CHARS)
            if it.get("opponent_summary"):
                topic.opponent_summary = _truncate(str(it["opponent_summary"]), MAX_SUMMARY_CHARS)
            topic.updated_at = datetime.utcnow()
        await db.flush()
        return await self.get_tree(db, meeting_id)

    @staticmethod
    def _parse_json_array(raw: str | None) -> list[dict]:
        if not raw:
            return []
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]
        try:
            data = json.loads(cleaned)
            return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []
