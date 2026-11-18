"""Подачи КП: документы объекта делятся на «подачи» (kind=offer, по папке подачи) и общий контекст.

Ключ подачи — documents.offer_submission (имя папки подачи; "" — документы вне папок подач).
NULL — документ общего контекста (ocr, расчёты TenderHub и т.п.).
"""

MAX_OFFER_SUBMISSION_LENGTH = 300
NO_FOLDER_LABEL = "Вне папок подач"


def offer_submission_from_meta(import_source: dict | None) -> str | None:
    """Ключ подачи по doc_meta.import_source: submission для kind=offer ("" если пусто), иначе None."""
    if not isinstance(import_source, dict) or import_source.get("kind") != "offer":
        return None
    submission = import_source.get("submission")
    if not isinstance(submission, str):
        return ""
    return submission.strip()[:MAX_OFFER_SUBMISSION_LENGTH]


def offer_submission_label(key: str) -> str:
    return key if key != "" else NO_FOLDER_LABEL


def public_doc_meta(doc_meta: dict | None) -> dict | None:
    """Копия doc_meta без import_source.path (локальный путь оператора не уходит в API)."""
    if not isinstance(doc_meta, dict):
        return doc_meta
    source = doc_meta.get("import_source")
    if not isinstance(source, dict) or "path" not in source:
        return doc_meta
    return {**doc_meta, "import_source": {k: v for k, v in source.items() if k != "path"}}
