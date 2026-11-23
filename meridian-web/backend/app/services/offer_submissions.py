"""Подачи КП: документы объекта делятся на «подачи» (kind=offer, по папке подачи) и общий контекст.

Ключ подачи — documents.offer_submission (имя папки подачи; "" — документы вне папок подач).
NULL — документ общего контекста (ocr, расчёты TenderHub и т.п.).
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.document import DocumentRecord

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


@dataclass
class ObjectOfferSubmission:
    key: str
    label: str
    date: str | None  # минимальная import_source.date группы (YYYY-MM-DD)
    document_count: int


async def list_object_offer_submissions(db: AsyncSession, object_id: int) -> list[ObjectOfferSubmission]:
    """Подачи КП объекта: группы документов по offer_submission (новые сверху)."""
    rows = (
        await db.execute(
            select(DocumentRecord.offer_submission, DocumentRecord.doc_meta).where(
                DocumentRecord.object_id == object_id,
                DocumentRecord.offer_submission.is_not(None),
            )
        )
    ).all()
    counts: dict[str, int] = {}
    dates: dict[str, str] = {}
    for key, doc_meta in rows:
        counts[key] = counts.get(key, 0) + 1
        source = doc_meta.get("import_source") if isinstance(doc_meta, dict) else None
        date = source.get("date") if isinstance(source, dict) else None
        if isinstance(date, str) and date and (key not in dates or date < dates[key]):
            dates[key] = date
    items = [
        ObjectOfferSubmission(
            key=key, label=offer_submission_label(key), date=dates.get(key), document_count=count,
        )
        for key, count in counts.items()
    ]
    items.sort(key=lambda g: g.key, reverse=True)
    items.sort(key=lambda g: g.date or "", reverse=True)  # без даты — в конце; ключи в группе по убыванию
    return items
