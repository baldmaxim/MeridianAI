"""RAG-клиент писем PayHub (внешнее read-only pgvector-хранилище).

Экспорт:
- embed_query(text) -> list[float]                        — Yandex query-эмбеддинг (dim=768, LRU)
- search_letters(query, k=8, project_id=None) -> [RagHit] — гибридный поиск (вектор+FTS+RRF)
- build_rag_context(hits) -> str                          — блок переписки для промпта LLM
- RagHit, LettersStore, get_store, close_store
"""

from .context import RagHit, build_rag_context
from .embeddings import embed_query
from .store import LettersStore, close_store, get_store, search_letters

__all__ = [
    "RagHit",
    "build_rag_context",
    "embed_query",
    "search_letters",
    "get_store",
    "close_store",
    "LettersStore",
]
