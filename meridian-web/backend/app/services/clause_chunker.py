# -*- coding: utf-8 -*-
"""Нарезка договора по пунктам.

Резать договор по страницам или по числу символов плохо: пункт рвётся на стыке страниц,
и модель видит обрывок («все ранее взысканные Застройщиком с…») и дописывает остальное сама.
Номер пункта оказывается в одном фрагменте, а его текст — в другом, и ссылка уезжает на соседний
пункт. Здесь фрагмент — это несколько пунктов целиком, в пределах одного раздела, со страницей
начала, разделом и списком номеров.

Если документ не похож на договор с нумерованными пунктами (письмо, смета), возвращаем None —
вызывающий режет по-старому.
"""

import re

# «13.2.1 Текст», «13.2.1. Текст», «5.1.1. Во избежание сомнений»
_CLAUSE_START = re.compile(r"^(?:п\.\s*)?(\d{1,2}(?:\.\d{1,3}){1,4})\.?\s+(?=\S)")
# «13. Порядок расчетов» — заголовок раздела: одно число и короткая строка
_SECTION_START = re.compile(r"^(\d{1,2})\.\s+([А-ЯЁA-Z«\"].{0,110})$")
_PAGE_NUMBER_LINE = re.compile(r"^\s*\d{1,4}\s*$")

MIN_CLAUSES = 8


class _Unit:
    """Пункт (или заголовок раздела, или преамбула) — строки с их страницами."""

    __slots__ = ("number", "section", "lines", "pages")

    def __init__(self, number: str | None, section: str | None):
        self.number = number
        self.section = section
        self.lines: list[str] = []
        self.pages: list[int | None] = []

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def is_clause(self) -> bool:
        return bool(self.number and "." in self.number)


def _lines_with_pages(segments: list[dict]):
    for seg in segments:
        lines = [ln.strip() for ln in (seg.get("text") or "").split("\n")]
        lines = [ln for ln in lines if ln]
        # колонтитул с номером страницы в начале или конце страницы — не часть пункта
        while lines and _PAGE_NUMBER_LINE.match(lines[-1]):
            lines.pop()
        while lines and _PAGE_NUMBER_LINE.match(lines[0]):
            lines.pop(0)
        for ln in lines:
            yield ln, seg.get("page_number")


def _section_for(clause_number: str, section: str | None) -> str | None:
    """Раздел пункта. Если заголовок раздела не распознан (скан, вёрстка), не приписываем
    пункт 13.2.1 предыдущему разделу «12. Цена Договора» — пишем «Раздел 13»."""
    top = clause_number.split(".")[0]
    if section and section.split(".")[0] == top:
        return section
    return f"Раздел {top}"


def _units(segments: list[dict]) -> list[_Unit]:
    units: list[_Unit] = []
    section: str | None = None
    current: _Unit | None = None
    for line, page in _lines_with_pages(segments):
        heading = _SECTION_START.match(line)
        clause = _CLAUSE_START.match(line)
        if heading and not clause:
            section = line
            current = _Unit(heading.group(1), section)
            units.append(current)
        elif clause:
            current = _Unit(clause.group(1), _section_for(clause.group(1), section))
            units.append(current)
        elif current is None:
            current = _Unit(None, None)  # преамбула до первого пункта
            units.append(current)
        current.lines.append(line)
        current.pages.append(page)
    return units


def _split_long(unit: _Unit, target_chars: int) -> list[_Unit]:
    """Длинный пункт (термины, преамбула) — на части по строкам, у каждой своя страница."""
    from .document_processing import chunk_text  # здесь: тот модуль импортирует этот

    parts: list[_Unit] = []
    part = _Unit(unit.number, unit.section)
    for line, page in zip(unit.lines, unit.pages):
        pieces = chunk_text(line, target_chars, 200) if len(line) > target_chars else [line]
        for piece in pieces:
            if part.lines and len(part.text) + len(piece) + 1 > target_chars:
                parts.append(part)
                part = _Unit(unit.number, unit.section)
            part.lines.append(piece)
            part.pages.append(page)
    if part.lines:
        parts.append(part)
    return parts


def chunk_by_clauses(segments: list[dict], target_chars: int = 1500,
                     max_unit_chars: int = 3000) -> list[dict] | None:
    """Фрагменты из целых пунктов: [{text, page, last_page, section, clauses}] или None."""
    units = _units(segments)
    if sum(1 for u in units if u.is_clause) < MIN_CLAUSES:
        return None

    rows: list[dict] = []
    batch: list[_Unit] = []

    def flush():
        if not batch:
            return
        clauses = list(dict.fromkeys(u.number for u in batch if u.is_clause))
        rows.append({
            "text": "\n".join(u.text for u in batch),
            "page": batch[0].pages[0],
            "last_page": batch[-1].pages[-1],
            "section": next((u.section for u in batch if u.section), None),
            "clauses": clauses,
        })
        batch.clear()

    def section_key(u: _Unit) -> str | None:
        return u.section.split(".")[0].replace("Раздел ", "") if u.section else None

    for unit in units:
        parts = _split_long(unit, target_chars) if len(unit.text) > max_unit_chars else [unit]
        for part in parts:
            size = sum(len(u.text) + 1 for u in batch)
            # заголовок раздела не уходит отдельным фрагментом — прилипает к первому пункту
            only_heading = bool(batch) and all(not u.is_clause and u.number and len(u.lines) == 1
                                               for u in batch)
            new_section = bool(batch) and section_key(part) != section_key(batch[-1])
            if batch and not only_heading and (new_section or size + len(part.text) > target_chars):
                flush()
            batch.append(part)
    flush()
    return rows
