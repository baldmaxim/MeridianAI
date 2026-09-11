"""Рендер страниц PDF и распознавание в LM Studio.

Почему не обычное извлечение текста: договоры приходят сканами, а у части PDF испорчен
текстовый слой — кириллица записана латинскими кодами («CTpOHTeJihHO» вместо «СТРОИТЕЛЬНО»).
Восстанавливать там нечего, страницу нужно прочитать глазами модели.

pypdfium2 (BSD/Apache, без системных зависимостей) рендерит страницу в PNG, chandra-ocr-2
возвращает Markdown со структурой и таблицами.
"""

from __future__ import annotations

import base64
import io
import threading
from typing import Any

import httpx

from meridian_ocr_agent.config import Config

OCR_PROMPT = (
    "Распознай весь текст на изображении. "
    "Сохрани структуру документа, заголовки, таблицы, списки и числовые значения. "
    "Верни результат в Markdown без лишних комментариев."
)

# pdfium не потокобезопасен даже для разных документов, а рендер идёт в потоках
# to_thread — поэтому обычная блокировка потоков, по одной странице за раз.
_RENDER_LOCK = threading.Lock()


class ModelUnavailable(Exception):
    """LM Studio не запущен или нужная модель не загружена — задачу брать нельзя."""


def page_count(pdf_bytes: bytes) -> int:
    import pypdfium2 as pdfium

    with _RENDER_LOCK:
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            return len(pdf)
        finally:
            pdf.close()


def render_page(pdf_bytes: bytes, index: int, dpi: int) -> bytes:
    """Страница → PNG в оттенках серого: вдвое меньше данных, текст не страдает.

    PDF передаётся байтами, а не путём: на Windows открытый файл нельзя удалить, и при
    прерванной задаче временная папка оставалась бы заблокированной потоком рендера.
    """
    import pypdfium2 as pdfium

    with _RENDER_LOCK:
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            page = pdf[index]
            try:
                bitmap = page.render(scale=dpi / 72)
                try:
                    buf = io.BytesIO()
                    bitmap.to_pil().convert("L").save(buf, format="PNG")
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
        newline = t.find("\n")
        t = t[newline + 1:] if newline != -1 else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _headers(config: Config) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.lmstudio_api_key}"} if config.lmstudio_api_key else {}


async def ensure_model(client: httpx.AsyncClient, config: Config) -> None:
    """Проверить до взятия задачи, что LM Studio отвечает и модель загружена.

    Иначе выключенная модель сжигала бы попытки распознавания: задача бралась бы в аренду
    и тут же проваливалась.
    """
    try:
        response = await client.get(f"{config.lmstudio_base_url}/models",
                                    headers=_headers(config), timeout=10)
    except httpx.HTTPError as cause:
        raise ModelUnavailable(f"LM Studio не отвечает на {config.lmstudio_base_url} "
                               f"({type(cause).__name__}) — запустите сервер в LM Studio") from cause
    if response.status_code == 401:
        raise ModelUnavailable("LM Studio требует ключ доступа — впишите lmstudio_api_key в настройки")
    if response.status_code != 200:
        raise ModelUnavailable(f"LM Studio ответил {response.status_code} на список моделей")
    ids = [m.get("id") for m in (response.json().get("data") or []) if isinstance(m, dict)]
    if config.model not in ids:
        raise ModelUnavailable(f"в LM Studio не загружена модель {config.model}; "
                               f"доступны: {', '.join(i for i in ids if i) or 'нет моделей'}")


async def recognize_page(client: httpx.AsyncClient, config: Config, png: bytes) -> str:
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    body: dict[str, Any] = {
        "model": config.model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        "temperature": 0,
    }
    response = await client.post(f"{config.lmstudio_base_url}/chat/completions", json=body,
                                  headers=_headers(config), timeout=config.page_timeout_seconds)
    response.raise_for_status()
    choices = response.json().get("choices") or []
    message = (choices[0].get("message") if choices else None) or {}
    return clean_ocr_text(message.get("content"))
