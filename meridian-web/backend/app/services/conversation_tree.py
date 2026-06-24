"""ConversationTreeService — дерево общения встречи.

Детерминированный слой: по committed-сегменту определяет сторону (наша/оппонент)
и тему по ключевым словам, делает upsert темы (без дублей). LLM-уточнение — по запросу.

Безопасность: тексты усечены, refs ограничены, в логи не пишем полный текст реплик.
"""

import json
import logging
import re
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.meeting_conversation import MeetingConversationTopic, STICKY_STATUSES, TOPIC_STATUSES
from ..models.meeting import TranscriptSegmentRecord
from ..schemas.conversation_tree import (
    ConversationTopicOut, ConversationTopicRef, ConversationTreeOut, ConversationTopicUpdate,
)
from .speaker_roles import to_public_side

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


def _slugify_key(raw: str) -> str:
    """Стабильный normalized_key (≤80 симв) из key/title LLM. Юникод (кириллица) допустим."""
    s = (raw or "").strip().lower()
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s or "topic")[:80]


def _side_tag(side: str | None) -> str:
    """Префикс стороны для строки стенограммы: [МЫ] / [НЕ МЫ] / ''."""
    pub = to_public_side(side)
    if pub == "self":
        return "[МЫ] "
    if pub == "opponent":
        return "[НЕ МЫ] "
    return ""


def build_tree_extraction_prompt(dialog_text: str, current_topics_json: str) -> str:
    """Промпт LLM-экстрактора условий (RU, строительная сфера)."""
    return (
        "Ты — ассистент переговоров в строительной сфере. По стенограмме встречи выдели и обнови\n"
        "список ОБСУЖДАЕМЫХ УСЛОВИЙ (тем). Для каждой темы укажи понятную позицию каждой стороны\n"
        "деловым предложением и 1–2 показательные цитаты (НЕ отдельные слова, а законченные фразы).\n\n"
        "Стороны: «МЫ» — наша сторона, «НЕ МЫ» — оппонент/заказчик.\n\n"
        "Уже выделенные темы (обнови их, не дублируй; сопоставляй по \"key\" или близкому смыслу):\n"
        f"{current_topics_json}\n\n"
        "Свежая стенограмма (каждая строка: [СТОРОНА] спикер: реплика):\n"
        f"{dialog_text}\n\n"
        "Правила:\n"
        "- НЕ выдумывай факты: только то, что реально сказано.\n"
        "- Объединяй однотемные реплики в ОДНУ тему; не плоди тему на каждое слово.\n"
        "- our_position / opponent_position — короткое деловое предложение (или null, если сторона не высказалась).\n"
        "- quotes — связные фразы из стенограммы, с указанием стороны (\"our\" или \"opponent\").\n"
        "- status: new | updated | resolved | disputed | needs_follow_up.\n"
        "- Если новых тем/изменений нет — верни пустой массив [].\n\n"
        "Верни ТОЛЬКО JSON-массив объектов строго такой формы:\n"
        "[{\"key\":\"price\",\"title\":\"Цена и стоимость\",\"our_position\":\"...\",\"opponent_position\":\"...\",\n"
        "  \"status\":\"disputed\",\"quotes\":[{\"side\":\"opponent\",\"speaker\":\"SM_S2\",\"text\":\"...\"}]}]"
    )


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
        """our | opponent | None (skip).

        UI v1 — две стороны «Мы»/«Не мы». ally исторически = наша сторона (our),
        third_party исторически = другая сторона (opponent).
        """
        if role in ("self", "ally"):
            return "our"
        if role in ("opponent", "third_party"):
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

    # ---------- LLM-экстрактор условий (live + offline) ----------

    async def extract_live(
        self, db: AsyncSession, meeting_id: int, *, dialog_text: str,
        current_topics: list[ConversationTopicOut], llm_client,
    ) -> tuple[list[ConversationTopicOut], bool]:
        """Главный LLM-проход: по связному диалогу выделить/обновить осмысленные темы-условия.

        Возвращает (изменённые_темы, ok). ok=False — нет ключа/ошибка/пустой ответ (no-op,
        вызывающий делает rollback). В логи НИКОГДА не пишем текст реплик/ответа (corp-no-secrets).
        """
        if llm_client is None or not (dialog_text or "").strip():
            return [], False
        compact = [{
            "id": t.id, "key": t.normalized_key, "title": t.title,
            "our": _truncate(t.our_summary or "", 200),
            "opponent": _truncate(t.opponent_summary or "", 200),
        } for t in current_topics]
        prompt = build_tree_extraction_prompt(dialog_text, json.dumps(compact, ensure_ascii=False))
        try:
            raw = await llm_client.get_suggestion_async(prompt, max_tokens=1400)
        except Exception as e:
            logger.warning("extract_live: meeting %s LLM error: %s", meeting_id, str(e)[:120])
            return [], False
        items = self._parse_json_array(raw)
        if not items:
            return [], False

        by_key = {t.normalized_key for t in current_topics}
        by_title = {(t.title or "").strip().lower(): t.normalized_key for t in current_topics}
        changed: list[ConversationTopicOut] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            if not title:
                continue
            raw_key = it.get("key")
            key = _slugify_key(str(raw_key)) if raw_key else _slugify_key(title)
            if key not in by_key:
                # тот же заголовок под другим ключом → переиспользовать существующий ключ (без дублей)
                key = by_title.get(title.lower(), key)
            quotes = it.get("quotes") if isinstance(it.get("quotes"), list) else []
            topic_out = await self._apply_llm_topic(
                db, meeting_id, key=key, title=title,
                our_position=it.get("our_position"), opponent_position=it.get("opponent_position"),
                status=str(it.get("status") or "").strip().lower(), quotes=quotes,
            )
            if topic_out is not None:
                changed.append(topic_out)
                by_key.add(topic_out.normalized_key)
                by_title[(topic_out.title or "").strip().lower()] = topic_out.normalized_key
        return changed, True

    async def _apply_llm_topic(
        self, db: AsyncSession, meeting_id: int, *, key: str, title: str,
        our_position, opponent_position, status: str, quotes: list,
    ) -> ConversationTopicOut | None:
        """Upsert темы по (meeting_id, normalized_key): позиции сторон + связные цитаты (НЕ пословно)."""
        topic = (await db.execute(
            select(MeetingConversationTopic).where(
                MeetingConversationTopic.meeting_id == meeting_id,
                MeetingConversationTopic.normalized_key == key,
            )
        )).scalar_one_or_none()
        now = datetime.utcnow()
        is_new = topic is None
        if is_new:
            topic = MeetingConversationTopic(
                meeting_id=meeting_id, title=_truncate(title, 255), normalized_key=key,
                status="new", last_updated_at=now, created_at=now, updated_at=now,
            )
            db.add(topic)
        else:
            topic.title = _truncate(title, 255)

        our_pos = our_position.strip() if isinstance(our_position, str) else ""
        opp_pos = opponent_position.strip() if isinstance(opponent_position, str) else ""
        if our_pos:
            topic.our_summary = _truncate(our_pos, MAX_SUMMARY_CHARS)
        if opp_pos:
            topic.opponent_summary = _truncate(opp_pos, MAX_SUMMARY_CHARS)

        our_refs: list[dict] = []
        opp_refs: list[dict] = []
        for q in quotes:
            if not isinstance(q, dict):
                continue
            text = str(q.get("text") or "").strip()
            if not text:
                continue
            side = to_public_side(q.get("side"))
            if side is None:
                continue
            ref = {"segment_id": "", "speaker": str(q.get("speaker") or ""),
                   "timecode": "", "text": _truncate(text, MAX_TEXT_CHARS)}
            (our_refs if side == "self" else opp_refs).append(ref)
        if our_refs:
            topic.our_refs_json = json.dumps(our_refs[-MAX_REFS_PER_SIDE:], ensure_ascii=False)
            topic.our_last_text = our_refs[-1]["text"]
        if opp_refs:
            topic.opponent_refs_json = json.dumps(opp_refs[-MAX_REFS_PER_SIDE:], ensure_ascii=False)
            topic.opponent_last_text = opp_refs[-1]["text"]

        if is_new:
            topic.status = status if status in TOPIC_STATUSES else "new"
        elif topic.status not in STICKY_STATUSES:
            topic.status = status if status in TOPIC_STATUSES else "updated"
        topic.last_updated_at = now
        await db.flush()
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
        unassigned = await self._unassigned_speakers(db, meeting_id)
        return ConversationTreeOut(meeting_id=meeting_id, tree_version=version,
                                   topics=topics, unassigned_speakers=unassigned)

    @staticmethod
    async def _unassigned_speakers(db: AsyncSession, meeting_id: int) -> list[str]:
        """Спикеры из persisted-транскрипта без назначенной стороны."""
        from .speaker_roles import get_roles_map
        rows = (await db.execute(
            select(TranscriptSegmentRecord.speaker_label, TranscriptSegmentRecord.speaker_id)
            .where(TranscriptSegmentRecord.session_id == meeting_id)
        )).all()
        speakers: list[str] = []
        seen = set()
        for label, spk_id in rows:
            name = label or spk_id
            if name and name not in seen:
                seen.add(name)
                speakers.append(name)
        roles = await get_roles_map(db, meeting_id)
        return [s for s in speakers if s not in roles]

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

        Роли спикеров берутся из БД (source of truth); можно переопределить аргументом.
        """
        if speaker_roles is None:
            from .speaker_roles import get_roles_map
            speaker_roles = await get_roles_map(db, meeting_id)
        speaker_roles = speaker_roles or {}
        # Этап 8: segment-level коррекции диаризации (overlay поверх speaker-роли)
        from .speaker_corrections import list_segment_corrections, resolve_speaker_for_segment
        corrections = await list_segment_corrections(db, meeting_id)
        await db.execute(delete(MeetingConversationTopic).where(
            MeetingConversationTopic.meeting_id == meeting_id))
        await db.flush()
        # Этап 9.8: если применялся cutover (есть эпохи) — пересобрать из авторитетного транскрипта
        try:
            from .transcription_authority_controller import build_authoritative_from_db
            auth = await build_authoritative_from_db(db, meeting_id)
        except Exception:
            auth = None
        if auth is not None and auth.segments:
            origin = min(a.start_ms for a in auth.segments)
            for a in auth.segments:
                sec = max(0, (a.start_ms - origin) // 1000)
                tc = f"{sec // 60:02d}:{sec % 60:02d}"
                await self.update_from_transcript_segment(
                    db, meeting_id, segment_id=a.segment_key, speaker=(a.speaker or ""),
                    role=a.side, text=a.text, timecode=tc)
            await db.flush()
            return await self.get_tree(db, meeting_id)
        segs = (await db.execute(
            select(TranscriptSegmentRecord)
            .where(TranscriptSegmentRecord.session_id == meeting_id)
            .order_by(TranscriptSegmentRecord.wall_clock.asc())
        )).scalars().all()
        for s in segs:
            original = s.speaker_label or s.speaker_id
            resolved = resolve_speaker_for_segment(s.segment_id, original, corrections, speaker_roles)
            speaker = resolved.effective_speaker_label or original
            role = resolved.side  # self|opponent|None (приоритет: коррекция реплики → роль)
            tc = f"{int(s.start_time or 0)//60:02d}:{int(s.start_time or 0)%60:02d}"
            await self.update_from_transcript_segment(
                db, meeting_id, segment_id=s.segment_id, speaker=speaker,
                role=role, text=s.text, timecode=tc,
            )
        await db.flush()
        return await self.get_tree(db, meeting_id)

    @staticmethod
    def _chunk_lines(lines: list[str], max_chars: int) -> list[str]:
        """Сгруппировать строки диалога в чанки ≤ max_chars (для длинных встреч)."""
        chunks: list[str] = []
        cur: list[str] = []
        cur_len = 0
        for ln in lines:
            if cur and cur_len + len(ln) + 1 > max_chars:
                chunks.append("\n".join(cur))
                cur, cur_len = [], 0
            cur.append(ln)
            cur_len += len(ln) + 1
        if cur:
            chunks.append("\n".join(cur))
        return chunks

    async def rebuild_with_llm(
        self, db: AsyncSession, meeting_id: int, llm_client, speaker_roles: dict[str, str] | None = None,
    ) -> ConversationTreeOut:
        """Offline-пересборка дерева через LLM из persisted-транскрипта.

        Нет LLM-клиента → детерминированный fallback (rebuild_from_segments)."""
        if llm_client is None:
            return await self.rebuild_from_segments(db, meeting_id, speaker_roles)
        if speaker_roles is None:
            from .speaker_roles import get_roles_map
            speaker_roles = await get_roles_map(db, meeting_id)
        speaker_roles = speaker_roles or {}
        from .speaker_corrections import list_segment_corrections, resolve_speaker_for_segment
        corrections = await list_segment_corrections(db, meeting_id)

        dialog_lines: list[str] = []
        try:
            from .transcription_authority_controller import build_authoritative_from_db
            auth = await build_authoritative_from_db(db, meeting_id)
        except Exception:
            auth = None
        if auth is not None and auth.segments:
            for a in auth.segments:
                text = (a.text or "").strip()
                if not text:
                    continue
                dialog_lines.append(f"{_side_tag(a.side)}{a.speaker or ''}: {text}")
        else:
            segs = (await db.execute(
                select(TranscriptSegmentRecord)
                .where(TranscriptSegmentRecord.session_id == meeting_id)
                .order_by(TranscriptSegmentRecord.wall_clock.asc())
            )).scalars().all()
            for s in segs:
                text = (s.text or "").strip()
                if not text:
                    continue
                original = s.speaker_label or s.speaker_id
                resolved = resolve_speaker_for_segment(s.segment_id, original, corrections, speaker_roles)
                spk = resolved.effective_speaker_label or original or ""
                dialog_lines.append(f"{_side_tag(resolved.side)}{spk}: {text}")

        await db.execute(delete(MeetingConversationTopic).where(
            MeetingConversationTopic.meeting_id == meeting_id))
        await db.flush()
        if not dialog_lines:
            return await self.get_tree(db, meeting_id)
        for chunk in self._chunk_lines(dialog_lines, max_chars=6000):
            tree = await self.get_tree(db, meeting_id)
            await self.extract_live(db, meeting_id, dialog_text=chunk,
                                    current_topics=tree.topics, llm_client=llm_client)
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
