"""Внешнее read-only pgvector-хранилище писем PayHub (схема ``rag``).

Отдельный asyncpg-пул (НЕ главный SQLAlchemy-engine): read-only роль, sslmode=verify-full
с CA из PGVECTOR_CA_CERT_PATH, server-side ``default_transaction_read_only=on``. Все запросы —
только параметризованные ($1,$2,$3). Никогда не пишем в схему ``rag``.

Гибридный поиск: вектор (cosine ``<=>``) + русский FTS, слияние RRF, диверсификация ≤2/письмо.
Мягкая деградация: ошибка эмбеддинга → только FTS; полный отказ → [].
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

from ...config import get_settings
from .context import RagHit
from .embeddings import embed_query
from .fusion import RRF_K, diversify, rrf_merge

logger = logging.getLogger("meridian.rag_letters")

_CANDIDATE_LIMIT = 50          # размер кандидат-листа для каждого канала
_QUERY_EMBED_MAX_CHARS = 1200  # тримминг длинного окна реплик перед эмбеддингом
_PER_LETTER = 2                # диверсификация: максимум чанков на одно письмо

# Векторный кандидат-лист (cosine). Вектор передаём строковым литералом pgvector с ::vector.
_VECTOR_SQL = """
SELECT c.chunk_id, c.letter_id, c.subject, c.reg_number, c.number, c.customer_number,
       c.direction, c.letter_date, c.project_id, c.page_from, c.page_to, c.content_original,
       1 - (e.embedding <=> $1::vector) AS score
  FROM rag.pg_embeddings e
  JOIN rag.corpus_chunks c ON c.chunk_id = e.chunk_id
 WHERE ($2::bigint IS NULL OR c.project_id = $2)
 ORDER BY e.embedding <=> $1::vector
 LIMIT $3
"""

# Лексический кандидат-лист (русский FTS + дострел по регистрационному номеру).
_FTS_SQL = """
WITH q AS (SELECT websearch_to_tsquery('russian', $1) AS tsq)
SELECT c.chunk_id, c.letter_id, c.subject, c.reg_number, c.number, c.customer_number,
       c.direction, c.letter_date, c.project_id, c.page_from, c.page_to, c.content_original,
       ts_rank_cd(c.search_vector, q.tsq) AS score
  FROM rag.corpus_chunks c CROSS JOIN q
 WHERE ($2::bigint IS NULL OR c.project_id = $2)
   AND (c.search_vector @@ q.tsq OR c.reg_number ILIKE '%' || $1 || '%')
 ORDER BY score DESC
 LIMIT $3
"""


# Имена таблицы/колонок проектов PayHub приходят из config (не из пользовательского ввода),
# но это идентификаторы — их нельзя биндить как $-параметры. Валидируем строго и квотируем.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROJECTS_LIMIT = 5000  # верхняя граница списка проектов на экране связки


def _safe_table(name: str) -> str:
    """Квотированный идентификатор таблицы (допускаем ``schema.table``)."""
    parts = (name or "").split(".")
    if not (1 <= len(parts) <= 2) or not all(_IDENT_RE.match(p) for p in parts):
        raise ValueError(f"некорректное имя таблицы проектов PayHub: {name!r}")
    return ".".join(f'"{p}"' for p in parts)


def _safe_col(name: str) -> str:
    if not _IDENT_RE.match(name or ""):
        raise ValueError(f"некорректное имя колонки PayHub: {name!r}")
    return f'"{name}"'


def _normalize_dsn(url: str) -> str:
    """asyncpg DSN: схема ``postgresql://`` без драйвера и без sslmode в query.

    asyncpg не понимает ``+asyncpg`` и параметры ``sslmode``/``sslrootcert`` в URL —
    TLS задаём отдельным ssl-контекстом.
    """
    parts = urlsplit(url)
    scheme = (parts.scheme.split("+", 1)[0]) or "postgresql"
    kept = [
        (k, v) for k, v in parse_qsl(parts.query)
        if k.lower() not in ("sslmode", "sslrootcert", "sslcert", "sslkey")
    ]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def _build_ssl_context(ca_path: str) -> ssl.SSLContext:
    """verify-full: проверка цепочки по корневому CA Yandex + проверка hostname."""
    ctx = ssl.create_default_context(cafile=ca_path or None)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _row_to_hit(row, score: float) -> RagHit:
    ld = row["letter_date"]
    if ld is None:
        letter_date = None
    elif hasattr(ld, "isoformat"):
        letter_date = ld.isoformat()
    else:
        letter_date = str(ld)
    lid = row["letter_id"]
    return RagHit(
        chunk_id=str(row["chunk_id"]),
        letter_id=str(lid) if lid is not None else None,
        subject=row["subject"],
        reg_number=row["reg_number"],
        number=row["number"],
        customer_number=row["customer_number"],
        direction=row["direction"],
        letter_date=letter_date,
        project_id=row["project_id"],
        page_from=row["page_from"],
        page_to=row["page_to"],
        text=row["content_original"] or "",
        score=round(float(score), 6),
    )


class LettersStore:
    """Ленивый пул к внешнему pgvector-хранилищу. Singleton на процесс (см. get_store)."""

    def __init__(self):
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        async with self._lock:
            if self._pool is not None:
                return self._pool
            s = get_settings()
            if not s.pgvector_db_url:
                raise RuntimeError("PGVECTOR_DB_URL не задан")
            self._pool = await asyncpg.create_pool(
                dsn=_normalize_dsn(s.pgvector_db_url),
                ssl=_build_ssl_context(s.pgvector_ca_cert_path),
                min_size=1,
                max_size=4,
                command_timeout=float(s.letters_search_timeout_seconds),
                # Yandex Managed PG фронтит pgbouncer (transaction pooling) — он несовместим
                # с кэшем prepared statements asyncpg. Отключаем кэш (как в app/database.py).
                statement_cache_size=0,
                # доп. защита поверх read-only роли: транзакции только на чтение
                server_settings={"default_transaction_read_only": "on"},
            )
            logger.info("rag_letters: pgvector pool initialized")
            return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def search_letters(
        self, query: str, k: int = 8, project_id: int | None = None
    ) -> list[RagHit]:
        """Гибридный (вектор+FTS, RRF, диверсификация) поиск писем. Возвращает top-k RagHit."""
        query = (query or "").strip()
        if not query:
            return []
        pool = await self._get_pool()

        # (a) векторный кандидат-лист (мягкая деградация: ошибка эмбеддинга → только FTS)
        vector_rows: list = []
        try:
            vec = await embed_query(query[:_QUERY_EMBED_MAX_CHARS])
            literal = "[" + ",".join(str(x) for x in vec) + "]"
            async with pool.acquire() as conn:
                vector_rows = await conn.fetch(_VECTOR_SQL, literal, project_id, _CANDIDATE_LIMIT)
        except Exception as e:
            logger.warning("rag_letters: vector search failed, falling back to FTS: %s", e)

        # (b) лексический кандидат-лист
        fts_rows: list = []
        try:
            async with pool.acquire() as conn:
                fts_rows = await conn.fetch(_FTS_SQL, query, project_id, _CANDIDATE_LIMIT)
        except Exception as e:
            logger.warning("rag_letters: FTS search failed: %s", e)

        if not vector_rows and not fts_rows:
            return []

        # (c) RRF-слияние по chunk_id
        by_id: dict = {}
        for r in list(vector_rows) + list(fts_rows):
            by_id.setdefault(r["chunk_id"], r)
        fused = rrf_merge(
            [[r["chunk_id"] for r in vector_rows], [r["chunk_id"] for r in fts_rows]],
            k_const=RRF_K,
        )
        ordered_ids = sorted(fused.keys(), key=lambda cid: fused[cid], reverse=True)

        # (d) диверсификация ≤2/письмо + top-k
        hits = [_row_to_hit(by_id[cid], fused[cid]) for cid in ordered_ids]
        hits = diversify(hits, per_letter=_PER_LETTER)
        return hits[:k]

    async def list_projects(self) -> list[dict]:
        """Список проектов PayHub (id, name, кол-во писем) для экрана связки.

        Тянет реальные названия из таблицы проектов PayHub (config: PAYHUB_PROJECTS_TABLE),
        обогащая числом писем из корпуса ``rag.corpus_chunks``. Read-only. Если таблица не
        настроена — возвращает [] (мягкая деградация: экран связки покажет «не настроено»).
        """
        s = get_settings()
        if not s.payhub_projects_table:
            return []
        table = _safe_table(s.payhub_projects_table)
        id_col = _safe_col(s.payhub_projects_id_col)
        name_col = _safe_col(s.payhub_projects_name_col)
        # Идентификаторы провалидированы regex + закавычены; значения не подставляются.
        sql = f"""
        SELECT p.{id_col} AS project_id,
               p.{name_col} AS name,
               COALESCE(lc.cnt, 0) AS letter_count
          FROM {table} p
          LEFT JOIN (
              SELECT project_id, count(DISTINCT letter_id) AS cnt
                FROM rag.corpus_chunks
               WHERE project_id IS NOT NULL
               GROUP BY project_id
          ) lc ON lc.project_id = p.{id_col}
         WHERE p.{id_col} IS NOT NULL
         ORDER BY p.{name_col}
         LIMIT {_PROJECTS_LIMIT}
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
        out: list[dict] = []
        for r in rows:
            name = r["name"]
            out.append({
                "projectId": int(r["project_id"]),
                "name": str(name) if name is not None else f"#{r['project_id']}",
                "letterCount": int(r["letter_count"]) if r["letter_count"] is not None else 0,
            })
        return out


_store: LettersStore | None = None


def get_store() -> LettersStore:
    global _store
    if _store is None:
        _store = LettersStore()
    return _store


async def search_letters(query: str, k: int = 8, project_id: int | None = None) -> list[RagHit]:
    """Удобная обёртка над singleton-store."""
    return await get_store().search_letters(query, k=k, project_id=project_id)


async def list_payhub_projects() -> list[dict]:
    """Список проектов PayHub (id, name, letterCount) для связки. Обёртка над singleton-store."""
    return await get_store().list_projects()


async def close_store() -> None:
    """Закрыть пул при shutdown приложения."""
    global _store
    if _store is not None:
        await _store.close()
        _store = None
