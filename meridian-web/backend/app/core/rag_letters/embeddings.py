"""Yandex query-эмбеддинги для поиска по письмам PayHub + LRU-кэш (вызовы платные).

Асимметричные эмбеддинги: индекс строился doc-моделью, ПОИСК идёт query-моделью
(YANDEX_EMBEDDING_QUERY_MODEL, dim=768). Запрос эмбеддим сырым — без обогащения метаданными.
Секреты (Api-Key/folder-id) НЕ логируем.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

import httpx

from ...config import get_settings

logger = logging.getLogger("meridian.rag_letters")


class _AsyncLRU:
    """Минималистичный async-safe LRU-кэш: текст запроса → вектор."""

    def __init__(self, maxsize: int):
        self.maxsize = max(1, int(maxsize))
        self._d: "OrderedDict[str, list[float]]" = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str):
        async with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
            return None

    async def put(self, key: str, value: list[float]) -> None:
        async with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)


_cache: _AsyncLRU | None = None


def _get_cache() -> _AsyncLRU:
    global _cache
    if _cache is None:
        _cache = _AsyncLRU(get_settings().letters_embedding_cache_size)
    return _cache


async def embed_query(text: str) -> list[float]:
    """Эмбеддинг запроса query-моделью Yandex (dim из конфига, обычно 768). Кэшируется по тексту.

    Бросает ValueError при несовпадении размерности — значит модель/dim рассинхронизированы
    с индексом, и поиск вернул бы мусор.
    """
    s = get_settings()
    key = (text or "").strip()
    if not key:
        raise ValueError("embed_query: пустой текст запроса")

    cache = _get_cache()
    cached = await cache.get(key)
    if cached is not None:
        return cached

    expected_dim = int(s.yandex_embedding_dim)
    payload = {
        "modelUri": s.yandex_embedding_query_model,
        "text": key,
        "dim": expected_dim,
    }
    headers = {
        "Authorization": f"Api-Key {s.yandex_api_key}",
        "x-folder-id": s.yandex_folder_id,
    }
    timeout = httpx.Timeout(float(s.yandex_embedding_timeout_seconds))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(s.yandex_embedding_endpoint, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    embedding = data.get("embedding")
    got = len(embedding) if isinstance(embedding, list) else None
    if got != expected_dim:
        raise ValueError(
            f"Yandex embedding dim mismatch: got {got}, expected {expected_dim} "
            f"(проверь YANDEX_EMBEDDING_QUERY_MODEL и YANDEX_EMBEDDING_DIM)"
        )
    vec = [float(x) for x in embedding]
    await cache.put(key, vec)
    return vec
