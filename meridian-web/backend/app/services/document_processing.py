"""Обработка документов (Этап 4): скачать из S3 → извлечь текст по сегментам
(страницы PDF / листы XLSX) → разбить на чанки → сохранить DocumentChunk.

Логируем только метаданные/размеры — НЕ полный текст документа (§: no-secrets/PII).
"""

import json
import logging
import re

from sqlalchemy import select, delete

from ..config import get_settings
from ..database import async_session
from ..models.document import DocumentRecord, DocumentChunk
from . import s3
from . import document_storage

from .document_text_quality import assess_extracted_text
from .clause_chunker import chunk_by_clauses
from .ocr_quality import ocr_page_warnings

logger = logging.getLogger("meridian.documents")

# Санитайзеры сообщения ошибки обработки (Этап 23): processing_error уходит в API-ответ
# (MeetingDocumentItem) и в логи → чистим presigned URL / x-amz / object key / длинные подписи,
# чтобы boto-ошибка не утекла клиенту/в логи. Собственные (безопасные) сообщения сохраняются.
_ERR_URL_RE = re.compile(r"https?://\S+")
_ERR_XAMZ_RE = re.compile(r"(?i)x-amz-\S+")
_ERR_KEY_RE = re.compile(r"(?i)\bkey\s+\S+")
_ERR_LONGTOK_RE = re.compile(r"[A-Za-z0-9/_+\-]{40,}")


def _safe_processing_error(exc: Exception) -> str:
    msg = str(exc)
    msg = _ERR_URL_RE.sub("[url]", msg)
    msg = _ERR_XAMZ_RE.sub("[redacted]", msg)
    msg = _ERR_KEY_RE.sub("key [redacted]", msg)
    msg = _ERR_LONGTOK_RE.sub("[redacted]", msg)
    return msg[:500]


# --- извлечение текста по сегментам (page/sheet metadata) ---

def _extract_segments(path: str, ext: str) -> tuple[list[dict], int | None, int | None]:
    """Вернуть (segments, page_count, sheet_count).

    segment = {"text": str, "page_number": int|None, "sheet_name": str|None}
    """
    ext = ext.lower()
    if ext in (".txt", ".md", ".csv"):
        text = _read_text(path)
        return ([{"text": text, "page_number": None, "sheet_name": None}], None, None)
    if ext == ".docx":
        return (_extract_docx(path), None, None)
    if ext == ".xlsx":
        segs = _extract_xlsx(path)
        return (segs, None, len(segs))
    if ext == ".pdf":
        segs = _extract_pdf(path)
        return (segs, len(segs), None)
    raise ValueError(f"Формат {ext} не поддерживается для извлечения текста")


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def _extract_docx(path: str) -> list[dict]:
    try:
        from docx import Document as DocxDocument
    except ImportError as e:
        raise RuntimeError("python-docx не установлен") from e
    doc = DocxDocument(path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    text = "\n\n".join(paragraphs)
    return [{"text": text, "page_number": None, "sheet_name": None}]


def _extract_xlsx(path: str) -> list[dict]:
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise RuntimeError("openpyxl не установлен") from e
    wb = load_workbook(path, read_only=True, data_only=True)
    segments: list[dict] = []
    try:
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                line = "\t".join(cells).rstrip()
                if line.strip():
                    rows.append(line)
            if rows:
                segments.append({
                    "text": f"[Лист: {sheet}]\n" + "\n".join(rows),
                    "page_number": None,
                    "sheet_name": sheet,
                })
    finally:
        wb.close()
    return segments


def _extract_pdf(path: str) -> list[dict]:
    try:
        from PyPDF2 import PdfReader
    except ImportError as e:
        raise RuntimeError("PyPDF2 не установлен") from e
    reader = PdfReader(path)
    segments: list[dict] = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append({"text": text, "page_number": i + 1, "sheet_name": None})
    if not segments:
        # пустой/сканированный PDF — вернём пустой сегмент, обработчик выдаст ошибку
        return []
    return segments


# --- чанкинг (char-based, с overlap) ---

def chunk_text(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    """Разбить текст на чанки ~target_chars с overlap_chars, по возможности по границам слов/строк."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= target_chars:
        return [text]
    overlap = max(0, min(overlap_chars, target_chars - 1))
    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + target_chars, n)
        if end < n:
            window_start = max(start + 1, end - overlap)
            br = text.rfind("\n", window_start, end)
            if br == -1:
                br = text.rfind(" ", window_start, end)
            if br > start:
                end = br
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def _build_chunk_rows(document_id: int, segments: list[dict], settings) -> list[dict]:
    """Фрагменты документа для поиска.

    Договор с нумерованными пунктами режем по пунктам (пункт не рвётся на стыке страниц,
    фрагмент знает свой раздел и номера). Остальное — по символам, как раньше.
    """
    cap = settings.document_max_extract_chars
    pieces: list[dict] = []
    by_clauses = chunk_by_clauses(segments) if settings.document_chunk_by_clauses else None
    if by_clauses:
        for r in by_clauses:
            meta = {"clauses": r["clauses"], "last_page": r["last_page"]}
            pieces.append({"text": r["text"], "page": r["page"], "sheet": None,
                           "section": (r["section"] or None) and r["section"][:300],
                           "metadata": json.dumps(meta, ensure_ascii=False)})
    else:
        for seg in segments:
            for piece in chunk_text(seg["text"], settings.document_chunk_target_chars,
                                    settings.document_chunk_overlap_chars):
                pieces.append({"text": piece, "page": seg["page_number"], "sheet": seg["sheet_name"]})
    rows: list[dict] = []
    total = 0
    for piece in pieces:
        if total + len(piece["text"]) > cap:
            logger.warning("document %s: достигнут лимит extract chars, обрезано", document_id)
            break
        rows.append({**piece, "idx": len(rows), "tokens": len(piece["text"].split())})
        total += len(piece["text"])
    logger.info("document %s: нарезка %s, фрагментов %d", document_id,
                "по пунктам" if by_clauses else "по символам", len(rows))
    return rows


# --- проверка текста и OCR ---

EMPTY_TEXT_MESSAGE = "Не удалось извлечь текст (пустой или сканированный документ)"


def _text_layer_problem(document_id: int, segments: list[dict]) -> str | None:
    """None — текст годится в контекст подсказок; иначе причина, почему нет.

    Нечитаемый текст (PDF без таблицы ToUnicode) нельзя пускать в контекст: поиск по нему не
    находит ничего, и LLM отвечает общими словами. Лучше честная ошибка, чем немой документ.
    """
    if sum(len(s["text"]) for s in segments) == 0:
        return EMPTY_TEXT_MESSAGE
    quality = assess_extracted_text("\n".join(seg["text"] for seg in segments))
    logger.info("document %s: букв=%s смешанный_регистр=%s кириллица=%s",
                document_id, quality.letters, quality.mixed_case_share, quality.cyrillic_share)
    return None if quality.ok else quality.message


async def _ocr_result(document_id: int) -> tuple[list[dict], int] | None:
    """Готовый текст от агента распознавания, если скан уже распознан."""
    from .ocr_queue import ocr_segments
    async with async_session() as db:
        return await ocr_segments(db, document_id)


async def _queue_for_ocr(document_id: int, page_count: int | None, problem: str) -> None:
    """Поставить скан в очередь агенту на компьютере пользователя.

    Сервер до локальной модели не достучится, поэтому не ждёт и не падает: документ
    получает статус «ждёт распознавания», а агент заберёт его сам, когда компьютер включён.
    """
    settings = get_settings()
    if page_count and page_count > settings.document_ocr_max_pages:
        raise ValueError(f"{problem} Распознавание не запущено: в документе {page_count} стр. — "
                         f"больше лимита {settings.document_ocr_max_pages}.")
    from .ocr_queue import request_ocr
    async with async_session() as db:
        doc = await db.get(DocumentRecord, document_id)
        if doc is None:
            return
        await request_ocr(db, doc)
        await db.commit()


# --- job handler ---

async def handle_document_process(payload: dict) -> None:
    document_id = payload["document_id"]
    settings = get_settings()
    local: str | None = None
    try:
        async with async_session() as db:
            doc = await db.get(DocumentRecord, document_id)
            if not doc:
                logger.warning("document %s not found", document_id)
                return
            if doc.status == "ready":
                return  # идемпотентность
            doc.status = "processing"
            await db.commit()
            s3_key, ext, original, owner = doc.s3_key, doc.file_ext, doc.original_name, doc.owner_user_id

        if not s3_key:
            raise ValueError("Документ без s3_key")

        ocr = await _ocr_result(document_id)
        if ocr is not None:
            # Скан уже распознан агентом — текстовый слой файла больше не нужен.
            segments, page_count = ocr
            sheet_count, text_source = None, "ocr"
        else:
            # secure temp download → extract → удалить в finally (§: no raw file persists)
            local = await document_storage.download_to_tempfile(s3_key, ext or "")
            segments, page_count, sheet_count = _extract_segments(local, ext or "")
            text_source = "text_layer"

        problem = _text_layer_problem(document_id, segments)
        if (problem and text_source == "text_layer" and (ext or "").lower() == ".pdf"
                and settings.document_ocr_enabled):
            await _queue_for_ocr(document_id, page_count, problem)
            logger.info("document %s: текстовый слой непригоден, ждёт агента распознавания", document_id)
            return
        if problem:
            raise ValueError(problem)

        chunk_rows = _build_chunk_rows(document_id, segments, settings)

        if not chunk_rows:
            raise ValueError("Не удалось сформировать чанки документа")

        # опционально: извлечённый текст целиком в S3
        extracted_key = None
        try:
            extracted_key = s3.object_key(owner, settings.s3_extracted_text_prefix, (original or "doc") + ".txt")
            full_text = "\n\n".join(s["text"] for s in segments)
            await s3.put_bytes(extracted_key, full_text.encode("utf-8"))
        except Exception as e:
            logger.info("document %s: extracted text upload skipped (%s)", document_id, type(e).__name__)
            extracted_key = None

        async with async_session() as db:
            doc = await db.get(DocumentRecord, document_id)
            if not doc:
                return
            await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            for r in chunk_rows:
                db.add(DocumentChunk(
                    document_id=document_id,
                    chunk_index=r["idx"],
                    text=r["text"],
                    page_number=r["page"],
                    sheet_name=r["sheet"],
                    section_title=r.get("section"),
                    token_count=r["tokens"],
                    metadata_json=r.get("metadata"),
                ))
            doc.status = "ready"
            doc.page_count = page_count
            doc.sheet_count = sheet_count
            doc.extracted_text_s3_key = extracted_key
            doc.processing_error = None
            # откуда текст: текстовый слой файла или OCR — видно при разборе качества поиска
            summary = {"text_source": text_source}
            if text_source == "ocr":
                summary["ocr_warnings"] = ocr_page_warnings(segments, page_count)
            doc.summary_json = json.dumps(summary, ensure_ascii=False)
            await db.commit()
        logger.info("document %s processed: %d chunks, pages=%s sheets=%s, source=%s",
                    document_id, len(chunk_rows), page_count, sheet_count, text_source)
    except Exception as e:
        safe_err = _safe_processing_error(e)
        logger.error("document %s processing failed: %s", document_id, safe_err)
        async with async_session() as db:
            doc = await db.get(DocumentRecord, document_id)
            if doc:
                doc.status = "error"
                doc.processing_error = safe_err
                await db.commit()
    finally:
        document_storage.cleanup_tempfile(local)
