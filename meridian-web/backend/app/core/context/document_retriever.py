"""Lexical document retriever — BM25-lite without external dependencies."""

import logging
import re
from typing import Dict, List, Set

from .document_chunker import DocumentChunk

logger = logging.getLogger("meridian.retriever")

# Doc types that get a relevance boost
_BOOSTED_TYPES = {"contract", "estimate", "bor"}
_BOOST_FACTOR = 1.3

# Minimal Russian stop-words (kept short to avoid over-filtering)
_STOP_WORDS: Set[str] = {
    "и", "в", "на", "с", "по", "для", "из", "к", "от", "за", "что",
    "не", "но", "а", "это", "то", "как", "же", "мы", "вы", "он", "она",
    "они", "я", "ты", "так", "уже", "да", "нет", "бы", "ли", "ещё",
    "если", "или", "до", "при", "об", "ко", "во", "все", "всё", "был",
    "быть", "его", "её", "их",
}

_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)


def _tokenize(text: str) -> List[str]:
    return [w for w in _TOKEN_RE.findall(text.lower()) if w not in _STOP_WORDS]


DOC_TYPE_LABELS = {
    "contract": "Договор",
    "bor": "ВОР",
    "estimate": "Смета",
    "specification": "Спецификация",
    "other": "Другое",
}


class DocumentRetriever:
    """In-memory lexical retriever over document chunks."""

    def __init__(self):
        self._chunks: List[DocumentChunk] = []
        self._chunk_tokens: List[Set[str]] = []

    def index(self, chunks: List[DocumentChunk]) -> None:
        """Add chunks to the index."""
        for chunk in chunks:
            self._chunks.append(chunk)
            self._chunk_tokens.append(set(_tokenize(chunk.text)))

    def remove(self, filename: str) -> None:
        """Remove all chunks belonging to a file."""
        keep = [(c, t) for c, t in zip(self._chunks, self._chunk_tokens)
                if c.filename != filename]
        if keep:
            self._chunks, self._chunk_tokens = list(zip(*keep))
            self._chunks = list(self._chunks)
            self._chunk_tokens = list(self._chunk_tokens)
        else:
            self._chunks = []
            self._chunk_tokens = []

    def retrieve(self, query: str, max_chunks: int = 5,
                 max_chars: int = 2000) -> str:
        """Retrieve top-scoring chunks for *query*, return formatted text."""
        if not self._chunks or not query.strip():
            return ""

        query_tokens = set(_tokenize(query))
        if not query_tokens:
            return ""

        scored: List[tuple[float, int]] = []
        for i, chunk_toks in enumerate(self._chunk_tokens):
            overlap = len(query_tokens & chunk_toks)
            if overlap == 0:
                continue
            score = overlap / len(query_tokens)
            if self._chunks[i].doc_type in _BOOSTED_TYPES:
                score *= _BOOST_FACTOR
            scored.append((score, i))

        scored.sort(key=lambda x: x[0], reverse=True)

        parts: List[str] = []
        total_chars = 0
        for score, idx in scored[:max_chunks]:
            chunk = self._chunks[idx]
            if total_chars + len(chunk.text) > max_chars:
                remaining = max_chars - total_chars
                if remaining < 100:
                    break
                text = chunk.text[:remaining] + "…"
            else:
                text = chunk.text
            header = self._format_header(chunk)
            parts.append(f"{header}\n{text}")
            total_chars += len(text)
            if total_chars >= max_chars:
                break

        if not parts:
            return ""
        result = "РЕЛЕВАНТНЫЕ ФРАГМЕНТЫ ДОКУМЕНТОВ:\n\n" + "\n\n".join(parts)
        logger.info("[Retriever] %d chunks selected (%d chars) for query len=%d",
                     len(parts), total_chars, len(query))
        return result

    def clear(self) -> None:
        self._chunks.clear()
        self._chunk_tokens.clear()

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @staticmethod
    def _format_header(chunk: DocumentChunk) -> str:
        label = DOC_TYPE_LABELS.get(chunk.doc_type, chunk.doc_type)
        meta = ""
        if chunk.page is not None:
            meta = f" (стр. {chunk.page})"
        elif chunk.section:
            meta = f" ({chunk.section})"
        return f"--- {label}: {chunk.filename}{meta} ---"
