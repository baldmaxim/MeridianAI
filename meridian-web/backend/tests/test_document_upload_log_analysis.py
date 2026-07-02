"""Этап 23: анализатор логов загрузки документов. Без БД/сети. Проверяем парс безопасных маркеров и
что сырые URL/ключи/имена/токены НЕ попадают в сводку."""

import json

from app.core.documents.document_upload_log_analysis import (
    analyze_document_upload_lines,
    extract_document_upload_event_from_line,
)

INITIATED = ("2026-07-01 10:00:00 INFO meridian.documents [DocumentS3Upload] initiated "
             "user_id=5 meeting_id=None content_type=application/pdf size=123 ext=.pdf ref=s3:abc1234567.pdf")
COMPLETED = ("2026-07-01 10:00:05 INFO meridian.documents [DocumentS3Upload] completed "
             "user_id=5 meeting_id=None size=123 ext=.pdf ref=s3:abc1234567.pdf")
LEGACY = "2026-07-01 10:01:00 INFO meridian.documents [DocumentS3Upload] legacy_fallback user_id=7"
PROCESSED = "2026-07-01 10:00:09 INFO meridian.documents document 42 processed: 3 chunks, pages=1 sheets=None"
FAILED_EMPTY = ("2026-07-01 10:00:09 ERROR meridian.documents document 42 processing failed: "
                "Не удалось извлечь текст (пустой или сканированный документ)")
FAILED_DOWNLOAD = ("2026-07-01 10:00:09 ERROR meridian.documents document 43 processing failed: "
                   "An error occurred (404) when calling the HeadObject operation on key "
                   "documents/secret_contract.pdf https://bucket.s3.amazonaws.com/documents/uuid.pdf?X-Amz-Signature=LEAKSIG")
URL_IN_INITIATED = ("2026-07-01 INFO [DocumentS3Upload] initiated user_id=5 meeting_id=None "
                    "content_type=application/pdf size=9 ext=.pdf ref=s3:z.pdf "
                    "https://bucket.s3.amazonaws.com/documents/uuid.pdf?X-Amz-Signature=LEAKSIG")


def test_extract_initiated():
    assert extract_document_upload_event_from_line(INITIATED) == {
        "event": "initiated", "content_type": "application/pdf", "size": 123, "ext": ".pdf"}


def test_extract_completed():
    ev = extract_document_upload_event_from_line(COMPLETED)
    assert ev["event"] == "completed" and ev["size"] == 123 and ev["ext"] == ".pdf"


def test_extract_legacy():
    assert extract_document_upload_event_from_line(LEGACY) == {"event": "legacy_fallback"}


def test_extract_processed():
    assert extract_document_upload_event_from_line(PROCESSED) == {"event": "processed", "chunks": 3}


def test_extract_failed_classifies_empty():
    ev = extract_document_upload_event_from_line(FAILED_EMPTY)
    assert ev == {"event": "processing_failed", "error_kind": "empty_or_scanned"}


def test_extract_failed_download_no_raw_leak():
    ev = extract_document_upload_event_from_line(FAILED_DOWNLOAD)
    assert ev["event"] == "processing_failed" and ev["error_kind"] == "download_error"
    blob = json.dumps(ev, ensure_ascii=False)
    for leak in ("LEAKSIG", "secret_contract", "documents/uuid.pdf", "amazonaws", "X-Amz-Signature"):
        assert leak not in blob


def test_extract_ignores_unrelated():
    assert extract_document_upload_event_from_line("random log line without markers") is None


def test_analyze_summary():
    lines = [INITIATED, INITIATED, COMPLETED, LEGACY, PROCESSED, FAILED_EMPTY]
    s = analyze_document_upload_lines(lines)
    assert s["initiated_count"] == 2
    assert s["completed_count"] == 1
    assert s["legacy_fallback_count"] == 1
    assert s["failed_count"] == 1
    assert s["by_error_kind"] == {"empty_or_scanned": 1}
    assert s["by_content_type"] == {"application/pdf": 2}
    assert s["by_extension"] == {".pdf": 2}
    assert s["completion_rate"] == 0.5


def test_analyze_raw_url_not_emitted():
    s = analyze_document_upload_lines([URL_IN_INITIATED])
    blob = json.dumps(s, ensure_ascii=False)
    for leak in ("LEAKSIG", "amazonaws", "X-Amz-Signature", "documents/uuid.pdf"):
        assert leak not in blob
    assert s["initiated_count"] == 1  # событие всё равно распознано


def test_analyze_no_events():
    s = analyze_document_upload_lines(["nothing here", ""])
    assert s["total"] == 0
    assert s["completion_rate"] is None
    assert "no_document_upload_events_found" in s["notes"]
