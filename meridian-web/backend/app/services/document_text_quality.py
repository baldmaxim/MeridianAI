# -*- coding: utf-8 -*-
"""Проверка, что из документа извлёкся читаемый текст, а не мусор.

Зачем. Часть PDF (сканы, «пересобранные» договоры) содержит текстовый слой без корректной
таблицы ToUnicode: кириллические глифы записаны латинскими кодами и извлекаются как
«CTpOHTeJihHO» вместо «СТРОИТЕЛЬНО». Такой документ раньше помечался ready, резался на чанки
и молча попадал в контекст подсказок: поиск по нему не находит НИЧЕГО (в тексте нет ни
«срок», ни «неустойка»), и LLM отвечает общими словами без ссылок на пункты договора.
Ни PyPDF2, ни pypdf, ни pdfminer такой файл не восстанавливают — нужен OCR.

Признак. У битого текста заглавные буквы стоят посреди слов («TepMHHOJiorust»,
«BhlDOJIUeuue»). На реальном договоре доля таких слов 0.81, у нормального русского,
английского и текста ЗАГЛАВНЫМИ — 0.00. Признак не зависит от языка, поэтому не бракует
англоязычные документы. Аббревиатуры вида «СНиП» его тоже задевают, но на документе
целиком их доля мала — отсюда запас между порогом 0.35 и наблюдаемыми 0.81.

Ограничение: ловим именно эту патологию. Мусор в одном регистре (сплошная
транслитерация) признаком не отсекается — такой случай закроет OCR-фаза.
"""

import re
from dataclasses import dataclass

# «слово» — только буквы (без цифр и подчёркиваний), в любом алфавите
_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

# Ниже этого числа букв не судим: у короткой выжимки признак шумит.
MIN_LETTERS_TO_JUDGE = 200
# Доля слов со «случайной» заглавной внутри, начиная с которой текст считаем битым.
BROKEN_MIXED_CASE_SHARE = 0.35

BROKEN_ENCODING_MESSAGE = (
    "Текст документа не читается: в PDF нет корректной таблицы шрифта, "
    "кириллица извлекается как латиница. Нужен OCR — загрузите распознанную версию."
)


@dataclass(frozen=True)
class TextQualityVerdict:
    """Результат проверки. ok=False → документ не должен становиться ready."""
    ok: bool
    reason: str  # "" | "broken_encoding"
    message: str
    letters: int
    mixed_case_share: float
    cyrillic_share: float


def letter_count(text: str | None) -> int:
    return sum(1 for c in (text or "") if c.isalpha())


def cyrillic_share(text: str | None) -> float:
    """Доля кириллицы среди букв (0..1). Диагностика для логов, не критерий."""
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0.0
    cyr = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    return round(cyr / len(letters), 3)


def mixed_case_word_share(text: str | None) -> float:
    """Доля слов (4+ букв) с заглавной НЕ в начале. Слова целиком капсом не считаются."""
    words = [w for w in _WORD_RE.findall(text or "") if len(w) >= 4]
    if not words:
        return 0.0
    broken = sum(1 for w in words if not w.isupper() and any(c.isupper() for c in w[1:]))
    return round(broken / len(words), 3)


def assess_extracted_text(text: str | None) -> TextQualityVerdict:
    """Годится ли извлечённый текст как контекст для подсказок."""
    letters = letter_count(text)
    mixed = mixed_case_word_share(text)
    cyr = cyrillic_share(text)
    broken = letters >= MIN_LETTERS_TO_JUDGE and mixed >= BROKEN_MIXED_CASE_SHARE
    return TextQualityVerdict(
        ok=not broken,
        reason="broken_encoding" if broken else "",
        message=BROKEN_ENCODING_MESSAGE if broken else "",
        letters=letters,
        mixed_case_share=mixed,
        cyrillic_share=cyr,
    )
