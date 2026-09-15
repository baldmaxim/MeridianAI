# -*- coding: utf-8 -*-
"""Разметка распознанной страницы → чистый текст.

chandra-ocr-2 отдаёт не Markdown, а HTML-вёрстку с координатами блоков:
`<div data-bbox="462 61 608 77" data-label="Section-Header"><h2>1. Терминология</h2></div>`.
В поиск по договору такое пускать нельзя: слова div, bbox, label и числа координат совпадают
с чем угодно, а текст раздувается в разы и вытесняет смысл из лимита контекста подсказок.

Структура сохраняется: блоки и заголовки — с новой строки, пункты списков — через «- »,
ячейки таблиц — через « | ». Если модель ответила обычным текстом или Markdown, он проходит
без изменений.
"""

import html
import json
import re
from html.parser import HTMLParser

_BLOCK = {"div", "p", "section", "article", "header", "footer", "h1", "h2", "h3", "h4", "h5",
          "h6", "ul", "ol", "table", "thead", "tbody", "tfoot", "blockquote", "pre", "figure",
          "figcaption", "caption"}
_SKIP = {"script", "style", "img", "svg", "math"}
_TAG_HINT = re.compile(r"<\s*(div|p|h[1-6]|table|tr|td|li|span|br)\b", re.IGNORECASE)
_DOUBLE_BULLET = re.compile(r"^-\s+[-–—•·]\s+")
_LAYOUT_JSON = re.compile(r'\[\s*\{\s*"label"\s*:.*?"bbox"\s*:.*?\}\s*\]', re.DOTALL)
_JSON_SKIP_ROLES = {"Page-Header", "Page-Footer"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.first_cell = True

    def _newline(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP:
            self.skip_depth += 1
        elif tag in _BLOCK or tag == "br":
            self._newline()
        elif tag == "li":
            self._newline()
            self.parts.append("- ")
        elif tag == "tr":
            self._newline()
            self.first_cell = True
        elif tag in ("td", "th"):
            if not self.first_cell:
                self.parts.append(" | ")
            self.first_cell = False

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br":
            self._newline()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in _BLOCK or tag in ("li", "tr"):
            self._newline()

    def handle_data(self, data):
        if self.skip_depth:
            return
        if data.strip():
            # внутри строки пробелы схлопываем; переносы задают теги, а не вёрстка исходника
            self.parts.append(re.sub(r"\s+", " ", data))


def _json_blocks_text(raw: str) -> str | None:
    """Страница целиком в виде [{"role": "Text", "text": "..."}, ...] → текст блоков.

    Колонтитулы (номер страницы) отбрасываем. None — это не такой формат.
    """
    stripped = raw.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return None
    try:
        blocks = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
        return None
    texts = [str(b.get("text") or "").strip() for b in blocks
             if str(b.get("role") or b.get("label") or "") not in _JSON_SKIP_ROLES]
    return "\n".join(t for t in texts if t)


def ocr_markup_to_text(raw: str | None) -> str:
    """Текст страницы без HTML-вёрстки OCR. Обычный текст и Markdown не трогает."""
    blocks_text = _json_blocks_text(raw or "")
    if blocks_text is not None:
        return ocr_markup_to_text(blocks_text) if _TAG_HINT.search(blocks_text) else blocks_text
    # Иногда модель вставляет служебный список блоков с координатами вместо текста:
    # [{"label": "Text", "bbox": "149 57 926 96"}, ...] — в поиске это чистый шум.
    text = _LAYOUT_JSON.sub(" ", raw or "")
    if not _TAG_HINT.search(text):
        return text.strip()
    parser = _TextExtractor()
    parser.feed(text)
    parser.close()
    lines = [line.strip() for line in "".join(parser.parts).split("\n")]
    cleaned = []
    for line in lines:
        # Пункт списка, где модель сама поставила тире («- - слова…»), — маркер один.
        line = _DOUBLE_BULLET.sub("- ", line)
        cleaned.append(re.sub(r"\s+\|\s*$", "", line))
    return html.unescape("\n".join(line for line in cleaned if line and line != "-")).strip()
