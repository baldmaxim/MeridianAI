# -*- coding: utf-8 -*-
"""OCR сканов через LM Studio.

Реальный случай: договор генподряда на 84 страницы — скан с испорченным текстовым слоем.
Без распознавания поиск по нему находит 0 фрагментов, и подсказки строятся без договора.
Сеть не трогаем: PDF генерируется на лету, сервер LM Studio подменяется.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.services import document_ocr
from app.services import document_processing as dp
from app.services.document_ocr import (
    OcrFailed,
    OcrUnavailable,
    clean_ocr_text,
    ocr_pdf,
    render_pdf_page,
)


@pytest.fixture
def pdf_path(tmp_path):
    """PDF из пустых страниц: рендер работает, OCR подменён."""
    def make(pages: int) -> str:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument.new()
        for _ in range(pages):
            pdf.new_page(595, 842)  # A4 в пунктах
        path = tmp_path / f"scan_{pages}.pdf"
        pdf.save(str(path))
        pdf.close()
        return str(path)
    return make


class FakeLMStudio:
    """Поддельный клиент: отвечает текстом по номеру вызова, умеет падать и считает параллельность."""

    def __init__(self, answers=None, fail_times=0, delay=0.0):
        self.answers = answers or {}
        self.fail_times = fail_times
        self.delay = delay
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.last_messages = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, *, model, messages, temperature, timeout):
        self.calls += 1
        self.last_messages = messages
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail_times > 0:
                self.fail_times -= 1
                raise ConnectionError("LM Studio недоступен")
            text = self.answers.get(self.calls, f"Страница, вызов {self.calls}")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
        finally:
            self.in_flight -= 1


# ---------- рендер и очистка ----------

def test_page_renders_to_png(pdf_path):
    png = render_pdf_page(pdf_path(1), 0, dpi=72)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("raw,expected", [
    ("```markdown\n# ДОГОВОР\nтекст\n```", "# ДОГОВОР\nтекст"),
    ("```\nтекст\n```", "текст"),
    ("  # ДОГОВОР  ", "# ДОГОВОР"),
    (None, ""),
])
def test_markdown_fence_is_removed(raw, expected):
    assert clean_ocr_text(raw) == expected


# ---------- распознавание ----------

async def test_every_page_becomes_a_segment_in_order(pdf_path):
    client = FakeLMStudio()
    segments, pages = await ocr_pdf(pdf_path(3), client=client)
    assert pages == 3
    assert [s["page_number"] for s in segments] == [1, 2, 3]
    assert all(s["sheet_name"] is None for s in segments)


async def test_request_carries_image_and_prompt(pdf_path):
    client = FakeLMStudio()
    await ocr_pdf(pdf_path(1), client=client)
    parts = client.last_messages[0]["content"]
    kinds = {p["type"] for p in parts}
    assert kinds == {"text", "image_url"}
    image = next(p for p in parts if p["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


async def test_blank_pages_are_skipped(pdf_path):
    client = FakeLMStudio(answers={1: "Пункт 7.3. Срок — 45 дней.", 2: "   "})
    segments, pages = await ocr_pdf(pdf_path(2), client=client)
    assert pages == 2
    assert len(segments) == 1 and "45 дней" in segments[0]["text"]


async def test_failed_page_is_retried_once(pdf_path):
    client = FakeLMStudio(fail_times=1)
    segments, _ = await ocr_pdf(pdf_path(1), client=client)
    assert client.calls == 2 and len(segments) == 1


async def test_page_failing_twice_fails_whole_document(pdf_path, monkeypatch):
    """Частичный текст опаснее отсутствующего: пропавшие пункты договора подсказка не заметит."""
    monkeypatch.setattr(get_settings(), "lmstudio_ocr_concurrency", 1)
    client = FakeLMStudio(fail_times=10)
    with pytest.raises(OcrFailed, match="страница 1"):
        await ocr_pdf(pdf_path(3), client=client)


async def test_concurrency_is_bounded(pdf_path, monkeypatch):
    """Сервер запущен с Parallel requests: 4 — больше запросов разом не шлём."""
    monkeypatch.setattr(get_settings(), "lmstudio_ocr_concurrency", 2)
    client = FakeLMStudio(delay=0.02)
    await ocr_pdf(pdf_path(6), client=client)
    assert client.max_in_flight <= 2


async def test_too_many_pages_is_refused_before_any_request(pdf_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "document_ocr_max_pages", 2)
    client = FakeLMStudio()
    with pytest.raises(OcrUnavailable, match="лимита"):
        await ocr_pdf(pdf_path(3), client=client)
    assert client.calls == 0


# ---------- доступность LM Studio ----------

async def test_ocr_unavailable_without_token(monkeypatch):
    async def no_keys():
        return {"openrouter": "x"}
    monkeypatch.setattr("app.services.api_keys.load_api_keys", no_keys)
    with pytest.raises(OcrUnavailable, match="токен"):
        await document_ocr.lmstudio_ocr_client()


async def test_ocr_can_be_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "document_ocr_enabled", False)
    with pytest.raises(OcrUnavailable, match="выключено"):
        await document_ocr.lmstudio_ocr_client()


# ---------- встраивание в обработку документа ----------

BROKEN = (
    "TepMHHOJiorust B HacTo.sn.a:eM ,.qorosope, ecm1 KOHTeKCT He npe,nnonaraeT HHoro "
    "CJIOBa 03Haqa10uu,1e e,nHHCTBeHHOe qlfCJIO BhlDOJIUeuue CTpOHTeJihHO MOHTruKHhIX "
    "pa6oT MaTepHaJIOB CTpOHTeJihCTBa O6opy)].OBaHIDI Heo6XO)].HMhIX BhmOJTHeHHR pa6oT "
    "TepMHHOJiorust KOHTeKCT npe,nnonaraeT BhlDOJIUeuue CTpOHTeJihHO MOHTruKHhIX MaTepHaJIOB"
)
NORMAL = (
    "Подрядчик обязуется выполнить строительно-монтажные работы в срок, установленный "
    "графиком производства работ. За нарушение срока Заказчик вправе начислить неустойку "
    "в размере ноль целых одна десятая процента от стоимости этапа за каждый день просрочки."
)


def _seg(text):
    return [{"text": text, "page_number": 1, "sheet_name": None}]


def test_readable_text_needs_no_ocr():
    assert dp._text_layer_problem(1, _seg(NORMAL)) is None


def test_broken_text_layer_is_a_problem():
    assert "OCR" in dp._text_layer_problem(1, _seg(BROKEN))


def test_empty_text_layer_is_a_problem():
    assert dp._text_layer_problem(1, _seg("")) == dp.EMPTY_TEXT_MESSAGE


async def test_unconfigured_ocr_explains_why(monkeypatch):
    async def unavailable(path):
        raise OcrUnavailable("не задан токен LM Studio в админке")
    monkeypatch.setattr(document_ocr, "ocr_pdf", unavailable)
    with pytest.raises(ValueError) as err:
        await dp._ocr_pdf_or_explain(1, "x.pdf", dp.EMPTY_TEXT_MESSAGE)
    msg = str(err.value)
    assert dp.EMPTY_TEXT_MESSAGE in msg and "токен LM Studio" in msg


async def test_ocr_failure_is_reported_as_retryable(monkeypatch):
    async def failed(path):
        raise OcrFailed("страница 5 не распозналась: ConnectionError")
    monkeypatch.setattr(document_ocr, "ocr_pdf", failed)
    with pytest.raises(ValueError, match="Повторите позже"):
        await dp._ocr_pdf_or_explain(1, "x.pdf", dp.EMPTY_TEXT_MESSAGE)


async def test_ocr_result_is_passed_through(monkeypatch):
    async def ok(path):
        return _seg(NORMAL), 1
    monkeypatch.setattr(document_ocr, "ocr_pdf", ok)
    segments, pages = await dp._ocr_pdf_or_explain(1, "x.pdf", dp.EMPTY_TEXT_MESSAGE)
    assert pages == 1 and dp._text_layer_problem(1, segments) is None
