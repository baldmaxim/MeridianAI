"""DocumentContextService (Этап 4): подбор релевантных чанков документов встречи
для LLM-подсказок. MVP — лексический BM25 по основам слов DocumentChunk.

Готово к будущему переходу на embeddings/vector search: интерфейс
get_relevant_chunks_for_meeting() стабилен, меняется только реализация scoring.
"""

import json
import logging
import math
import re
from collections import Counter
from itertools import zip_longest

from sqlalchemy import and_, case, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import async_session
from ..models.meeting import MeetingDocumentRecord, MeetingSession
from ..models.document import DocumentRecord, DocumentChunk
from .offer_submissions import offer_submission_label

logger = logging.getLogger("meridian.documents")

_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)
_STEM_LEN = 5
# Разговорные и служебные слова реплики: в договоре они случайно совпадают с чем угодно.
_STOP_WORDS = frozenset(
    "это эти этот эта этом этого того тем том там тут как так что чтобы если или либо для при "
    "про над под без через после перед между также тоже уже еще все всех весь вся всего каждый "
    "каждого каждой был была были будет будем будут есть нет них ним нам вам вас ваш вашу ваша "
    "ваше наш нашу наша они она оно его ему мне меня себя свой свою своих который которые "
    "которая только очень даже можно нужно надо сейчас завтра сегодня вчера здесь тогда когда "
    "пока".split()
)
# BM25: насыщение частоты слова и поправка на длину фрагмента.
_BM25_K1 = 1.2
_BM25_B = 0.75


def _stems(text: str) -> list[str]:
    """Основы слов: «удерживать», «удержание», «удерживает» → «удерж».

    Русские окончания иначе ломают совпадение: реплика «будем удерживать» не находила
    пункт договора «Застроитель ежемесячно удерживает 3%». Грубое усечение вместо
    морфологии — без новых зависимостей, коллизии гасит вес редкости слова.
    """
    words = _TOKEN_RE.findall((text or "").lower().replace("ё", "е"))
    return [w[:_STEM_LEN] for w in words if len(w) >= 3 and w not in _STOP_WORDS]


def _bm25_scores(query_text: str, texts: list[str]) -> list[float]:
    """BM25 по основам слов. Учитывает, сколько раз слово стоит во фрагменте:
    пункт, целиком посвящённый удержанию, важнее страницы, где оно упомянуто вскользь.
    Частые слова договора («работ», «договор») почти ничего не весят.
    """
    query = set(_stems(query_text))
    docs = [Counter(_stems(t)) for t in texts]
    if not query or not docs:
        return [0.0] * len(texts)
    n = len(docs)
    avg_len = (sum(sum(d.values()) for d in docs) / n) or 1.0
    idf = {}
    for term in query:
        df = sum(term in d for d in docs)
        idf[term] = math.log(1 + (n - df + 0.5) / (df + 0.5))
    scores = []
    for d in docs:
        norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * sum(d.values()) / avg_len)
        scores.append(sum(idf[t] * d[t] * (_BM25_K1 + 1) / (d[t] + norm) for t in query if d[t]))
    return scores


def _chunk_clauses(metadata_json: str | None) -> list[str]:
    """Номера пунктов фрагмента (нарезка по пунктам) — для подписи фрагмента в промпте."""
    if not metadata_json:
        return []
    try:
        clauses = json.loads(metadata_json).get("clauses")
    except (ValueError, AttributeError):
        return []
    return [str(c) for c in clauses] if isinstance(clauses, list) else []


# Буст bm25 для чанков документов подачи КП (общий контекст объекта идёт без буста).
OFFER_SUBMISSION_BOOST = 1.35

# Приоритет унаследованного документа (у него нет строки meeting_documents) — как у прикреплённого.
DEFAULT_DOCUMENT_PRIORITY = 100

# Bound text transferred to the API and tokenized by BM25. Keep small document
# sets unchanged; large PostgreSQL corpora first use native lexical ranking.
RETRIEVAL_CANDIDATES_PER_QUERY = 512


def _stem_pattern(term: str) -> str:
    # Match the same word alphabet as _TOKEN_RE, including apostrophes. A five
    # character stem accepts word endings; shorter tokens match the whole word.
    boundary = "[^[:alnum:]_']"
    return "(^|" + boundary + ")" + re.escape(term) + ("($|" + boundary + ")" if len(term) < _STEM_LEN else "")


def _candidate_query(stmt, query: str, priority, cap: int):
    terms = sorted(set(_stems(query)))
    if not terms:
        return None
    # Materialize normalization once. Ranking uses only boolean hits and IDs;
    # the API receives text for the bounded candidates, never the entire corpus.
    normalized = func.replace(func.lower(DocumentChunk.text), "ё", "е")
    corpus = stmt.with_only_columns(
        DocumentChunk.id, normalized.label("normalized"), priority.label("priority"),
        DocumentChunk.chunk_index,
    ).cte("context_corpus").prefix_with("MATERIALIZED")
    hits = select(
        corpus.c.id, corpus.c.priority, corpus.c.chunk_index,
        *(corpus.c.normalized.op("~")(_stem_pattern(term)).label(f"hit_{i}")
          for i, term in enumerate(terms)),
    ).cte("context_hits").prefix_with("MATERIALIZED")
    flags = [hits.c[f"hit_{i}"] for i in range(len(terms))]
    stats = select(
        func.count().label("total"),
        *(func.sum(case((flag, 1), else_=0)).label(f"df_{i}") for i, flag in enumerate(flags)),
    ).cte("context_stats")
    # Global rarity prevents frequent contract words from crowding out a rare
    # operative term. BM25 still performs the final frequency/length ranking.
    score = sum(case((flag, func.ln(1 + (stats.c.total - stats.c[f"df_{i}"] + 0.5)
                                    / (stats.c[f"df_{i}"] + 0.5))), else_=0)
                for i, flag in enumerate(flags))
    ids = select(hits.c.id).join(stats, true()).where(or_(*flags)).order_by(
        score.desc(), hits.c.priority.desc(), hits.c.chunk_index, hits.c.id,
    ).limit(cap)
    return stmt.where(DocumentChunk.id.in_(ids))


async def _candidate_rows(db: AsyncSession, stmt, query_text: str, extra_query: str):
    # SQLite exists only in unit tests; production requires PostgreSQL.
    if db.get_bind().dialect.name != "postgresql":
        return (await db.execute(stmt)).all()
    cap = RETRIEVAL_CANDIDATES_PER_QUERY
    probe = (await db.execute(stmt.limit(cap + 1))).all()
    if len(probe) <= cap:
        return probe
    priority = func.coalesce(func.nullif(MeetingDocumentRecord.priority, 0), DEFAULT_DOCUMENT_PRIORITY)
    if not _stems(query_text):
        return (await db.execute(stmt.order_by(
            (priority / 100000.0 - DocumentChunk.chunk_index / 1000000.0).desc(), DocumentChunk.id,
        ).limit(cap))).all()

    rows, seen = [], set()
    # Separate pools preserve direct hits when topic expansion has many matches.
    for query in dict.fromkeys((query_text, extra_query)):
        candidates_stmt = _candidate_query(stmt, query, priority, cap)
        if candidates_stmt is None:
            continue
        candidates = (await db.execute(candidates_stmt)).all()
        for row in candidates:
            if row.id not in seen:
                seen.add(row.id)
                rows.append(row)
    return rows


def inherited_documents_stmt(meeting: MeetingSession):
    """SELECT DocumentRecord.id готовых документов заказчика/объекта встречи (или None).

    Документы общие для всех сотрудников (services/access.py), поэтому фильтра по пользователю нет:
    Документ объекта наследуется его встречами (при выбранной подаче КП — общие + только её).
    Документ заказчика без привязки к объекту наследуется встречами этого заказчика.
    """
    conds = []
    if meeting.customer_id is not None:
        conds.append(and_(
            DocumentRecord.customer_id == meeting.customer_id,
            DocumentRecord.object_id.is_(None),
        ))
    if meeting.object_id is not None:
        object_cond = DocumentRecord.object_id == meeting.object_id
        if meeting.offer_submission is not None:
            # обсуждается одна подача КП: общий контекст объекта (NULL) + документы только этой подачи
            object_cond = and_(object_cond, or_(
                DocumentRecord.offer_submission.is_(None),
                DocumentRecord.offer_submission == meeting.offer_submission,
            ))
        conds.append(object_cond)
    if not conds:
        return None
    return select(DocumentRecord.id).where(DocumentRecord.status == "ready", or_(*conds))


async def effective_meeting_document_ids(db: AsyncSession, meeting: MeetingSession) -> set[int]:
    """Документы, попадающие в контекст встречи.

    Прикреплённые (included=true) ∪ готовые документы её заказчика/объекта, кроме тех, у кого
    есть строка meeting_documents (included=false — пользователь убрал документ из этой встречи).
    """
    rows = (
        await db.execute(
            select(MeetingDocumentRecord.document_id, MeetingDocumentRecord.included).where(
                MeetingDocumentRecord.session_id == meeting.id,
                MeetingDocumentRecord.document_id.isnot(None),
            )
        )
    ).all()
    with_row = {doc_id for doc_id, _ in rows}
    ids = {doc_id for doc_id, included in rows if included}
    inherited = inherited_documents_stmt(meeting)
    if inherited is not None:
        ids |= {i for i in (await db.execute(inherited)).scalars().all() if i not in with_row}
    return ids


async def get_relevant_chunks_for_meeting(
    db: AsyncSession, meeting_id: int, query_text: str, limit: int = 6, extra_query: str = "",
) -> list[dict]:
    """Top-N релевантных чанков среди included+ready документов встречи.

    Источники: прикреплённые (included=true) и унаследованные от заказчика/объекта документы
    (effective_meeting_document_ids) → DocumentRecord(status='ready') → DocumentChunk.
    extra_query — формулировки темы в языке договора (document_query). Выдачи по реплике и по
    формулировкам чередуются: прямые попадания по реплике не вытесняются, а находится и то,
    с чем у реплики нет общих слов.
    """
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return []
    doc_ids = await effective_meeting_document_ids(db, meeting)
    if not doc_ids:
        return []
    stmt = (
        select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.text,
                DocumentChunk.page_number,
                DocumentChunk.sheet_name,
                DocumentChunk.section_title,
                DocumentChunk.metadata_json,
                DocumentRecord.original_name,
                DocumentRecord.offer_submission,
                func.coalesce(MeetingDocumentRecord.priority, DEFAULT_DOCUMENT_PRIORITY).label("priority"),
            )
            .join(DocumentRecord, DocumentRecord.id == DocumentChunk.document_id)
            .outerjoin(
                MeetingDocumentRecord,
                (MeetingDocumentRecord.document_id == DocumentRecord.id)
                & (MeetingDocumentRecord.session_id == meeting_id),
            )
            .where(
                DocumentRecord.id.in_(doc_ids),
                DocumentRecord.status == "ready",
            )
    )
    rows = await _candidate_rows(db, stmt, query_text, extra_query)
    if not rows:
        return []

    ranked = _rank_rows(rows, query_text, meeting.offer_submission)
    if extra_query.strip() and _stems(query_text):
        merged, seen = [], set()
        for pair in zip_longest(ranked, _rank_rows(rows, extra_query, meeting.offer_submission)):
            for item in pair:
                if item is not None and item[1].id not in seen:
                    seen.add(item[1].id)
                    merged.append(item)
        ranked = merged
    out: list[dict] = []
    for score, r in ranked[:limit]:
        out.append({
            "document_id": r.document_id,
            "document_name": r.original_name,
            "chunk_id": r.id,
            "text": r.text,
            "page_number": r.page_number,
            "sheet_name": r.sheet_name,
            "section_title": r.section_title,
            "clauses": _chunk_clauses(r.metadata_json),
            "score": round(float(score), 4),
        })
    return out


def _is_offer_chunk(row_submission: str | None, meeting_submission: str | None) -> bool:
    """Чанк документа подачи КП? Подача встречи задана — только её документы; иначе — любая подача."""
    if meeting_submission:
        return row_submission == meeting_submission
    return bool(row_submission)


def _rank_rows(rows, query_text: str, meeting_submission: str | None = None) -> list[tuple[float, object]]:
    has_query = bool(_stems(query_text))
    bm25 = _bm25_scores(query_text, [r.text for r in rows]) if has_query else []
    scored: list[tuple[float, object]] = []
    for i, r in enumerate(rows):
        priority_boost = (r.priority or 100) / 100000.0  # лёгкий приоритетный буст
        if not has_query:
            # пустой запрос → начало документов (по приоритету и порядку)
            score = priority_boost - r.chunk_index / 1_000_000.0
        else:
            if bm25[i] <= 0:
                continue
            # Документы подачи КП поднимаем над общим контекстом (bm25 > 0 — нерелевантные не трогаем)
            relevance = bm25[i]
            if _is_offer_chunk(getattr(r, "offer_submission", None), meeting_submission):
                relevance *= OFFER_SUBMISSION_BOOST
            score = relevance + priority_boost
            # бонус за вхождение фразы (биграммы запроса)
            low = r.text.lower()
            ql = query_text.lower()
            if len(ql) >= 6 and ql[:40] and ql[:40] in low:
                score += 0.2
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def format_chunks_block(chunks: list[dict], max_chunks: int, max_chars: int) -> str:
    """Сформировать промпт-блок 'Релевантные фрагменты документов:' с лимитами."""
    if not chunks:
        return ""
    parts: list[str] = []
    total = 0
    for c in chunks[:max_chunks]:
        loc = ""
        if c.get("page_number"):
            loc = f" | Страница {c['page_number']}"
        elif c.get("sheet_name"):
            loc = f" | Лист: {c['sheet_name']}"
        if c.get("section_title"):
            loc += f" | {c['section_title']}"
        clauses = c.get("clauses") or []
        if clauses:
            loc += " | Пункты " + (clauses[0] if len(clauses) == 1 else f"{clauses[0]}–{clauses[-1]}")
        header = f"[Документ: {c['document_name']}{loc}]"
        text = c["text"]
        if total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining < 200:
                break
            text = text[:remaining].rstrip() + "…"
        parts.append(f"{header}\n{text}")
        total += len(text)
        if total >= max_chars:
            break
    if not parts:
        return ""
    return "Релевантные фрагменты документов:\n\n" + "\n\n".join(parts)


async def build_meeting_doc_context(meeting_id: int, query_text: str, extra_query: str = "") -> str:
    """Провайдер для SessionManager: вернуть готовый промпт-блок (или '').

    Открывает собственную сессию БД (вызывается из STT/LLM-движка).
    """
    settings = get_settings()
    try:
        async with async_session() as db:
            chunks = await get_relevant_chunks_for_meeting(
                db, meeting_id, query_text, limit=settings.document_context_max_chunks,
                extra_query=extra_query,
            )
            meeting = await db.get(MeetingSession, meeting_id)
            submission = meeting.offer_submission if meeting is not None else None
        block = format_chunks_block(
            chunks, settings.document_context_max_chunks, settings.document_context_max_chars
        )
        if block and submission is not None:
            block = f"Обсуждаемая подача КП: {offer_submission_label(submission)}\n\n{block}"
        return block
    except Exception as e:
        logger.error("doc context build failed for meeting %s: %s", meeting_id, e)
        return ""
