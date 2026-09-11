# -*- coding: utf-8 -*-
"""OCR сканов через LM Studio (chandra-ocr-2).

Зачем. Договоры часто приходят сканами с испорченным текстовым слоем: кириллица записана
латинскими кодами («CTpOHTeJihHO» вместо «СТРОИТЕЛЬНО»). Ни PyPDF2, ни pypdf, ни pdfminer
такое не восстанавливают — восстанавливать нечего. Без распознавания документ немой:
поиск по нему находит 0 фрагментов, и подсказки строятся без опоры на пункты договора.

Как. Страницы рендерятся в PNG (pypdfium2) и по одной уходят в chandra-ocr-2 на сервере
LM Studio пользователя. Результат — те же сегменты {text, page_number}, что и у обычного
извлечения, поэтому чанкинг, S3 и поиск работают без изменений.

Ограничения, заложенные в код:
  - pdfium не потокобезопасен: рендер строго по одной странице под общей блокировкой,
    параллелятся только запросы к модели;
  - одновременно в памяти не больше `lmstudio_ocr_concurrency` картинок — скан на 80+
    страниц иначе съел бы сотни мегабайт;
  - неудачная страница повторяется один раз, потом падает весь документ. Частичный текст
    опаснее отсутствующего: подсказка сослалась бы на договор, в котором пропали пункты.
"""

import asyncio
import base64
import io
import logging
import threading

from ..config import get_settings

logger = logging.getLogger("meridian.ocr")

OCR_PROMPT = (
    "Распознай весь текст на изображении. "
    "Сохрани структуру документа, заголовки, таблицы, списки и числовые значения. "
    "Верни результат в Markdown без лишних комментариев."
)

# pdfium не потокобезопасен даже для разных документов — рендерим строго по одному.
# Именно threading.Lock: рендер идёт в потоках to_thread, а asyncio.Lock на уровне модуля
# привязался бы к первому event loop и ломался в следующем.
_RENDER_LOCK = threading.Lock()


class OcrUnavailable(RuntimeError):
    """Автоматическое распознавание не может начаться (не настроено / слишком большой документ)."""


class OcrFailed(RuntimeError):
    """Распознавание началось, но не удалось (сервер недоступен, страница не распозналась)."""


def _page_count(path: str) -> int:
    import pypdfium2 as pdfium
    with _RENDER_LOCK:
        pdf = pdfium.PdfDocument(path)
        try:
            return len(pdf)
        finally:
            pdf.close()


def render_pdf_page(path: str, index: int, dpi: int) -> bytes:
    """Страница PDF → PNG в оттенках серого. Синхронно, потокобезопасно (общая блокировка)."""
    import pypdfium2 as pdfium
    with _RENDER_LOCK:
        return _render_locked(pdfium, path, index, dpi)


def _render_locked(pdfium, path: str, index: int, dpi: int) -> bytes:
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[index]
        try:
            bitmap = page.render(scale=dpi / 72)
            try:
                image = bitmap.to_pil().convert("L")  # серый: вдвое меньше данных, текст не страдает
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                return buf.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        pdf.close()


def clean_ocr_text(text: str | None) -> str:
    """Снять markdown-обёртку ```…```, если модель завернула в неё ответ."""
    t = (text or "").strip()
    if t.startswith("```"):
        first_nl = t.find(chr(10))
        t = t[first_nl + 1:] if first_nl != -1 else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


async def lmstudio_ocr_client():
    """Клиент LM Studio для OCR или OcrUnavailable с понятной причиной."""
    settings = get_settings()
    if not settings.document_ocr_enabled:
        raise OcrUnavailable("автоматическое распознавание выключено (DOCUMENT_OCR_ENABLED)")
    from .api_keys import load_api_keys
    token = (await load_api_keys()).get("lm_studio")
    if not token:
        raise OcrUnavailable("не задан токен LM Studio в админке")
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=token, base_url=settings.lmstudio_base_url,
                       timeout=settings.lmstudio_ocr_timeout_seconds, max_retries=0)


async def ocr_page_image(client, png: bytes, *, model: str, timeout: float) -> str:
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    response = await client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        temperature=0,
        timeout=timeout,
    )
    return clean_ocr_text(response.choices[0].message.content)


async def ocr_pdf(path: str, *, client=None) -> tuple[list[dict], int]:
    """Распознать PDF целиком. Возвращает (сегменты по страницам, число страниц)."""
    settings = get_settings()
    client = client or await lmstudio_ocr_client()

    pages = await asyncio.to_thread(_page_count, path)
    if pages > settings.document_ocr_max_pages:
        raise OcrUnavailable(
            f"в документе {pages} стр. — больше лимита распознавания "
            f"{settings.document_ocr_max_pages} (DOCUMENT_OCR_MAX_PAGES)")

    semaphore = asyncio.Semaphore(max(1, settings.lmstudio_ocr_concurrency))
    model = settings.lmstudio_ocr_model
    timeout = float(settings.lmstudio_ocr_timeout_seconds)

    async def one(index: int) -> str:
        async with semaphore:  # сначала слот — чтобы в памяти не копились картинки
            png = await asyncio.to_thread(render_pdf_page, path, index, settings.lmstudio_ocr_dpi)
            last_error: Exception | None = None
            for attempt in (1, 2):
                try:
                    return await ocr_page_image(client, png, model=model, timeout=timeout)
                except Exception as e:  # сеть/сервер/модель — одна повторная попытка
                    last_error = e
                    logger.warning("OCR стр. %s, попытка %s: %s", index + 1, attempt, type(e).__name__)
            raise OcrFailed(f"страница {index + 1} не распозналась: {type(last_error).__name__}")

    # TaskGroup, а не gather: при провале страницы остальные запросы отменяются, а не
    # продолжают грузить сервер LM Studio ради документа, который всё равно упадёт.
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(one(i)) for i in range(pages)]
    except ExceptionGroup as eg:  # наружу — одна понятная ошибка, а не группа
        first = eg.exceptions[0]
        if isinstance(first, (OcrFailed, OcrUnavailable)):
            raise first from None
        raise OcrFailed(f"распознавание прервалось: {type(first).__name__}") from first
    texts = [t.result() for t in tasks]
    segments = [
        {"text": text, "page_number": i + 1, "sheet_name": None}
        for i, text in enumerate(texts) if text
    ]
    logger.info("OCR: страниц %s, с текстом %s, символов %s",
                pages, len(segments), sum(len(s["text"]) for s in segments))
    return segments, pages
