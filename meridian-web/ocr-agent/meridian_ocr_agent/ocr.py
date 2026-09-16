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
import re
import threading
from dataclasses import dataclass
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


_OVERFLOW_MARKERS = ("context", "n_ctx", "too many tokens", "token limit", "exceeds")


class LmStudioError(Exception):
    """LM Studio ответил ошибкой. Хранит код и текст ответа — без них причину не понять."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"LM Studio {status}: {detail}")

    @property
    def context_overflow(self) -> bool:
        """Запрос не влез в контекст модели — помогает только картинка поменьше."""
        low = self.detail.lower()
        return self.status in (400, 413, 422, 500) and any(m in low for m in _OVERFLOW_MARKERS)


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            error = error.get("message") or error
        text = str(error or data)
    except ValueError:
        text = response.text
    return " ".join(text.split())[:300] or "пустой ответ"


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


_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_LETTER = re.compile(r"[А-Яа-яЁёA-Za-z]")
_HTML_TAG = re.compile(r"<[^>]*>")
_LAYOUT_JSON = re.compile(r'\[\s*\{\s*"label"\s*:.*?"bbox"\s*:.*?\}\s*\]', re.DOTALL)
MIN_PAGE_LETTERS = 3  # в ответе из одних координат блоков после снятия разметки букв нет


def clean_ocr_text(text: str | None) -> str:
    """Снять markdown-обёртку ```…```, если модель завернула в неё ответ."""
    t = (text or "").strip()
    if t.startswith("```"):
        newline = t.find("\n")
        t = t[newline + 1:] if newline != -1 else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def strip_reasoning_preamble(text: str) -> str:
    """«The user wants me to recognize the text…<p>Текст» → «<p>Текст».

    В поле рассуждений перед разметкой страницы модель пишет, что собирается делать. Режем
    только нерусский кусок перед первым тегом — сам текст договора не трогаем.
    """
    tag = text.find("<")
    if tag > 0 and not _CYRILLIC.search(text[:tag]):
        return text[tag:].strip()
    return text


def has_page_text(text: str) -> bool:
    """Есть ли в ответе текст страницы, а не одна разметка блоков.

    На реальном договоре модель вернула для стр. 53 только список блоков с координатами
    ([{"label": "Text", "bbox": "149 57 926 96"}, …]) — это не распознанная страница, её надо
    повторить в другом разрешении, как пустой ответ.
    """
    stripped = _HTML_TAG.sub(" ", _LAYOUT_JSON.sub(" ", text or ""))
    return len(_LETTER.findall(stripped)) >= MIN_PAGE_LETTERS


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


# Куда сборки LM Studio складывают «размышления» модели. У vision-модели, чей шаблон
# открывает <think>, весь ответ может уехать сюда, а content останется пустым.
REASONING_FIELDS = ("reasoning_content", "reasoning", "thinking")
_THINK_TAG = re.compile(r"</?think>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PageAnswer:
    text: str
    source: str  # content | reasoning_content | … | пусто
    diagnostics: str


async def recognize_page(client: httpx.AsyncClient, config: Config, png: bytes) -> str:
    return (await recognize_page_detailed(client, config, png)).text


async def recognize_page_detailed(client: httpx.AsyncClient, config: Config, png: bytes) -> PageAnswer:
    """Распознать страницу и объяснить, откуда взят текст — или почему его нет."""
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
    if response.status_code >= 400:
        raise LmStudioError(response.status_code, _error_detail(response))
    data = response.json()
    choices = data.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}

    text, source = clean_ocr_text(message.get("content")), "content"
    if not text:
        source = "пусто"
        for field in REASONING_FIELDS:
            alt = strip_reasoning_preamble(clean_ocr_text(_THINK_TAG.sub("", str(message.get(field) or ""))))
            if alt:
                text, source = alt, field
                break
    if text and not has_page_text(text):
        text, source = "", f"{source}, но только разметка блоков без текста"

    usage = data.get("usage") or {}
    lengths = ", ".join(f"{f}={len(str(message.get(f) or ''))}" for f in ("content",) + REASONING_FIELDS
                        if f in message)
    diagnostics = (f"finish_reason={choice.get('finish_reason')}; поля ответа: {lengths or 'нет'}; "
                   f"completion_tokens={usage.get('completion_tokens')}; текст взят из: {source}")
    return PageAnswer(text=text, source=source, diagnostics=diagnostics)
