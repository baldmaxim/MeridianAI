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
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_ONLY_DOTS = re.compile(r"^[.…\s]+$")
_YOD_IN_WORD = re.compile(r"(?<=[а-яё])י+(?=[а-яё])", re.IGNORECASE)
_MIXED_WORD = re.compile(r"\b(?=\w*[а-яё])(?=\w*[a-z])\w+\b", re.IGNORECASE)
_LATIN_TO_CYRILLIC = str.maketrans("aAeEoOpPcCxXyYkKmMTHBr", "аАеЕоОрРсСхХуУкКмМТНВр")
_JSON_ROLE_START = re.compile(r'\[\s*\{\s*"role"\s*:')
_JSON_BLOCK_SPLIT = re.compile(r'\}\s*,\s*\{')
_JSON_ROLE = re.compile(r'\s*"role"\s*:\s*"([^"]*)"\s*,?')
_JSON_VALUE_KEY = re.compile(r'"(?:text|list)"\s*:\s*\[?')
_JSON_STRING_SEP = re.compile(r'"\s*\]?\s*,\s*\[?\s*"')


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
        return _broken_json_blocks_text(stripped)
    if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
        return None
    texts = []
    for b in blocks:
        if str(b.get("role") or b.get("label") or "") in _JSON_SKIP_ROLES:
            continue
        value = b.get("text") if b.get("text") is not None else b.get("list")
        items = value if isinstance(value, list) else [value]
        texts += [str(item or "").strip() for item in items]
    return "\n".join(t for t in texts if t)


def _broken_json_blocks_text(raw: str) -> str | None:
    """Тот же список блоков, но невалидный JSON.

    Модель не экранирует кавычки внутри текста («штампом "В производство работ"») и путает
    скобки в списках. Режем по границам блоков и вынимаем из каждого все строки.
    """
    if not _JSON_ROLE_START.match(raw):
        return None
    texts = []
    for piece in _JSON_BLOCK_SPLIT.split(raw.strip()[1:-1].strip().strip("{}")):
        role = _JSON_ROLE.match(piece)
        if role is None:
            continue
        if role.group(1) in _JSON_SKIP_ROLES:
            continue
        rest = _JSON_VALUE_KEY.sub("", piece[role.end():])
        for part in _JSON_STRING_SEP.split(rest):
            part = part.strip().strip('[]"').strip()
            if part:
                texts.append(part)
    return "\n".join(texts) if texts else None


def _fix_alphabet_mixups(text: str) -> str:
    """«Застроייщик» → «Застройщик», «видеокamer» → «видеокамер».

    Модель путает похожие буквы чужих алфавитов, и поиск по слову их не находит.
    Меняем только внутри русских слов — английские термины и коды не трогаем.
    """
    text = _YOD_IN_WORD.sub("й", text)
    return _MIXED_WORD.sub(lambda m: m.group(0).translate(_LATIN_TO_CYRILLIC), text)


def ocr_markup_to_text(raw: str | None) -> str:
    """Текст страницы без HTML-вёрстки OCR. Обычный текст и Markdown не трогает."""
    return _fix_alphabet_mixups(_markup_to_text(raw))


def _markup_to_text(raw: str | None) -> str:
    blocks_text = _json_blocks_text(raw or "")
    if blocks_text is not None:
        return _markup_to_text(blocks_text) if _TAG_HINT.search(blocks_text) else blocks_text
    # Иногда модель вставляет служебный список блоков с координатами вместо текста:
    # [{"label": "Text", "bbox": "149 57 926 96"}, ...] — в поиске это чистый шум.
    text = _LAYOUT_JSON.sub(" ", raw or "")
    first_tag = _TAG_HINT.search(text)
    if first_tag and first_tag.start() > 0 and not _CYRILLIC.search(text[:first_tag.start()]):
        # Ответ из поля рассуждений: «The user wants me to recognize the text…» перед разметкой.
        text = text[first_tag.start():]
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
    # «-» — пустой пункт списка, «...» — пример разметки из рассуждения модели («like <p>...</p>»)
    return html.unescape("\n".join(line for line in cleaned
                                   if line and line != "-" and not _ONLY_DOTS.match(line))).strip()
