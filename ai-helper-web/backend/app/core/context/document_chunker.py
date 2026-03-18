"""Document chunker — splits document text into chunks with metadata."""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .document_loader import MeetingDocument

logger = logging.getLogger("ai_helper.chunker")

TARGET_CHUNK_SIZE = 500  # chars


@dataclass
class DocumentChunk:
    """Single chunk of a document."""

    chunk_id: str          # "{filename}:{idx}"
    filename: str
    doc_type: str
    text: str
    page: Optional[int]    # PDF page number (1-based)
    section: Optional[str] # MD heading / xlsx sheet name


_MD_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)", re.MULTILINE)
_PAGE_MARKER = "\n\n"  # _extract_pdf joins pages with this


class DocumentChunker:
    """Splits a MeetingDocument into chunks."""

    def __init__(self, target_size: int = TARGET_CHUNK_SIZE):
        self._target = target_size

    def chunk(self, doc: "MeetingDocument") -> List[DocumentChunk]:
        ext = doc.filename.rsplit(".", 1)[-1].lower() if "." in doc.filename else ""

        if ext == "md":
            chunks = self._chunk_md(doc)
        elif ext == "pdf":
            chunks = self._chunk_pdf(doc)
        else:
            chunks = self._chunk_plain(doc)

        logger.info("[Chunker] %d chunks from %s", len(chunks), doc.filename)
        return chunks

    # ------------------------------------------------------------------
    # Format-specific chunking
    # ------------------------------------------------------------------

    def _chunk_pdf(self, doc: "MeetingDocument") -> List[DocumentChunk]:
        """Split PDF text by pages, then merge small pages."""
        pages = doc.content.split(_PAGE_MARKER)
        raw: list[tuple[str, int]] = []  # (text, page_number)
        for i, page_text in enumerate(pages, 1):
            text = page_text.strip()
            if text:
                raw.append((text, i))

        return self._merge_and_build(raw, doc, key_field="page")

    def _chunk_md(self, doc: "MeetingDocument") -> List[DocumentChunk]:
        """Split MD by headings."""
        parts: list[tuple[str, str | None]] = []
        current_section: str | None = None
        current_lines: list[str] = []

        for line in doc.content.split("\n"):
            m = _MD_HEADING_RE.match(line)
            if m:
                # Flush previous section
                text = "\n".join(current_lines).strip()
                if text:
                    parts.append((text, current_section))
                current_section = m.group(2).strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        # Flush last section
        text = "\n".join(current_lines).strip()
        if text:
            parts.append((text, current_section))

        return self._merge_and_build(parts, doc, key_field="section")

    def _chunk_plain(self, doc: "MeetingDocument") -> List[DocumentChunk]:
        """Split plain text (txt/docx/xlsx) by double newlines."""
        paragraphs = re.split(r"\n{2,}", doc.content)
        raw = [(p.strip(), None) for p in paragraphs if p.strip()]
        return self._merge_and_build(raw, doc, key_field=None)

    # ------------------------------------------------------------------
    # Merge small pieces into target-sized chunks
    # ------------------------------------------------------------------

    def _merge_and_build(
        self,
        parts: list[tuple],
        doc: "MeetingDocument",
        key_field: Optional[str],
    ) -> List[DocumentChunk]:
        chunks: List[DocumentChunk] = []
        buf_text = ""
        buf_key = parts[0][1] if parts else None
        idx = 0

        for text, key in parts:
            if buf_text and (len(buf_text) + len(text) > self._target):
                # Flush buffer
                chunks.append(self._build_chunk(
                    idx, doc, buf_text, key_field, buf_key))
                idx += 1
                buf_text = text
                buf_key = key
            else:
                if buf_text:
                    buf_text += "\n\n" + text
                else:
                    buf_text = text
                    buf_key = key

        if buf_text:
            chunks.append(self._build_chunk(
                idx, doc, buf_text, key_field, buf_key))

        return chunks

    @staticmethod
    def _build_chunk(
        idx: int,
        doc: "MeetingDocument",
        text: str,
        key_field: Optional[str],
        key_value,
    ) -> DocumentChunk:
        return DocumentChunk(
            chunk_id=f"{doc.filename}:{idx}",
            filename=doc.filename,
            doc_type=doc.doc_type,
            text=text,
            page=key_value if key_field == "page" else None,
            section=key_value if key_field == "section" else None,
        )
