"""Document upload log analyzer (Этап 23).

Парсит БЕЗОПАСНЫЕ маркеры логов загрузки документов и выдаёт агрегированную сводку. По построению
НЕ хранит сырую строку лога: извлекает только распознанные безопасные поля (event/content_type/ext/
size/chunks/error_kind). Поэтому presigned URL / token / S3 key / имя файла / текст документа в вывод
не попадают, даже если оказались в исходной строке.

Маркеры (точные форматы из app/api/documents.py и app/services/document_processing.py):
  [DocumentS3Upload] initiated user_id=… meeting_id=… content_type=<ct> size=<n> ext=<e> ref=<r>
  [DocumentS3Upload] completed user_id=… meeting_id=… size=<n> ext=<e> ref=<r>
  [DocumentS3Upload] legacy_fallback user_id=…
  document <id> processed: <n> chunks, pages=… sheets=…
  document <id> processing failed: <msg>   (msg классифицируется в error_kind, не эхоится)

CLI: python -m app.core.documents.document_upload_log_analysis /path/app.log [--output out.json]
Exit: 0 ок; 2 файл не найден/ошибка I/O; 3 неверные аргументы.
"""

import argparse
import json
import re
import sys
from collections import Counter

_RE_INITIATED = re.compile(
    r"\[DocumentS3Upload\]\s+initiated\b.*?content_type=(?P<ct>\S+)\s+size=(?P<size>\d+)\s+ext=(?P<ext>\S*)")
_RE_COMPLETED = re.compile(
    r"\[DocumentS3Upload\]\s+completed\b.*?size=(?P<size>\d+)\s+ext=(?P<ext>\S*)")
_RE_LEGACY = re.compile(r"\[DocumentS3Upload\]\s+legacy_fallback\b")
_RE_PROCESSED = re.compile(r"document\s+\S+\s+processed:\s+(?P<chunks>\d+)\s+chunks\b")
_RE_FAILED = re.compile(r"document\s+\S+\s+processing failed:\s+(?P<msg>.*)$")

# Классификация ошибки обработки по подстроке. Сырой текст ошибки НЕ сохраняется (может содержать
# S3-ключ/URL из boto-исключения) — только безопасный bucket.
_ERROR_KIND_RULES = [
    ("empty_or_scanned", ("не удалось извлечь текст", "пустой", "сканирован")),
    ("no_chunks", ("не удалось сформировать чанки",)),
    ("unsupported_format", ("не поддерживается", "формат")),
    ("missing_key", ("без s3_key",)),
    ("download_error", ("download", "clienterror", "endpointconnection", "s3", "botocore", "404", "nosuchkey")),
]


def _classify_error_kind(msg: str | None) -> str:
    low = (msg or "").lower()
    for kind, needles in _ERROR_KIND_RULES:
        if any(n in low for n in needles):
            return kind
    return "other"


def _norm_content_type(ct: str | None) -> str:
    ct = (ct or "").strip().lower()
    if not ct or ct == "-":
        return "unknown"
    return ct[:80]


def _norm_ext(ext: str | None) -> str:
    ext = (ext or "").strip().lower()
    return ext[:16] if ext else "none"


def extract_document_upload_event_from_line(line: str) -> dict | None:
    """Извлечь безопасное событие из одной строки лога или None. Сырую строку не возвращает."""
    if not line or "[DocumentS3Upload]" not in line and "processing failed" not in line \
            and " processed:" not in line:
        return None
    m = _RE_INITIATED.search(line)
    if m:
        return {"event": "initiated",
                "content_type": _norm_content_type(m.group("ct")),
                "size": int(m.group("size")),
                "ext": _norm_ext(m.group("ext"))}
    m = _RE_COMPLETED.search(line)
    if m:
        return {"event": "completed", "size": int(m.group("size")), "ext": _norm_ext(m.group("ext"))}
    if _RE_LEGACY.search(line):
        return {"event": "legacy_fallback"}
    m = _RE_PROCESSED.search(line)
    if m:
        return {"event": "processed", "chunks": int(m.group("chunks"))}
    m = _RE_FAILED.search(line)
    if m:
        # msg только классифицируем, не сохраняем
        return {"event": "processing_failed", "error_kind": _classify_error_kind(m.group("msg"))}
    return None


def load_document_upload_events_from_lines(lines) -> list[dict]:
    out: list[dict] = []
    for line in lines or []:
        ev = extract_document_upload_event_from_line(str(line))
        if ev is not None:
            out.append(ev)
    return out


def analyze_document_upload_events(events: list[dict]) -> dict:
    events = events or []
    initiated = [e for e in events if e.get("event") == "initiated"]
    completed = [e for e in events if e.get("event") == "completed"]
    legacy = [e for e in events if e.get("event") == "legacy_fallback"]
    failed = [e for e in events if e.get("event") == "processing_failed"]

    by_content_type = dict(Counter(e["content_type"] for e in initiated))
    by_extension = dict(Counter(e["ext"] for e in initiated))
    by_error_kind = dict(Counter(e.get("error_kind", "other") for e in failed))

    initiated_count = len(initiated)
    completed_count = len(completed)
    completion_rate = round(completed_count / initiated_count, 4) if initiated_count else None

    notes: list[str] = []
    if initiated_count == 0 and completed_count == 0 and not legacy:
        notes.append("no_document_upload_events_found")
    if initiated_count and completed_count > initiated_count:
        notes.append("completed_exceeds_initiated (возможна ротация лога)")
    if failed:
        notes.append("processing_failures_present")
    if legacy:
        notes.append("legacy_fallback_used")
    if completion_rate is not None and completion_rate < 0.5:
        notes.append("low_completion_rate")

    return {
        "total": len(events),
        "initiated_count": initiated_count,
        "completed_count": completed_count,
        "legacy_fallback_count": len(legacy),
        "failed_count": len(failed),
        "by_content_type": by_content_type,
        "by_extension": by_extension,
        "by_error_kind": by_error_kind,
        "completion_rate": completion_rate,
        "notes": notes,
    }


def analyze_document_upload_lines(lines) -> dict:
    return analyze_document_upload_events(load_document_upload_events_from_lines(lines))


def _main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser(
        prog="python -m app.core.documents.document_upload_log_analysis",
        description="Безопасный анализатор логов загрузки документов (Этап 23).")
    parser.add_argument("logfile")
    parser.add_argument("--output", default=None)
    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3
    try:
        with open(ns.logfile, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Файл не найден: {ns.logfile}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return 2
    summary = analyze_document_upload_lines(lines)
    blob = json.dumps(summary, ensure_ascii=False, indent=2)
    if ns.output:
        try:
            with open(ns.output, "w", encoding="utf-8") as f:
                f.write(blob)
        except OSError as e:
            print(f"Ошибка записи: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"written": ns.output, "total": summary["total"]}, ensure_ascii=False))
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
