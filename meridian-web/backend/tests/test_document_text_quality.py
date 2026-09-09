# -*- coding: utf-8 -*-
"""Документ с нечитаемым текстовым слоем не должен становиться контекстом подсказок.

Реальный случай: договор генподряда на 84 страницы извлёкся как «CTpOHTeJihHO» вместо
«СТРОИТЕЛЬНО» (PDF без таблицы ToUnicode). Документ помечался ready, поиск по нему не
находил ни «срок», ни «неустойка», и подсказки строились вообще без договора.
"""

import pytest

from app.services.document_text_quality import (
    BROKEN_ENCODING_MESSAGE,
    MIN_LETTERS_TO_JUDGE,
    assess_extracted_text,
    cyrillic_share,
    mixed_case_word_share,
)

# Форма совпадает с реальным извлечением: заглавные посреди слов, кириллицы нет.
BROKEN = (
    "TepMHHOJiorust B HacTo.sn.a:eM ,.qorosope, ecm1 KOHTeKCT He npe,nnonaraeT HHoro: "
    "CJIOBa, 03Haqa10uu,1e e,nHHCTBeHHOe qlfCJIO, BhlDOJIUeuue CTpOHTeJihHO MOHTruKHhIX "
    "pa6oT MaTepHaJIOB ):(JUI CTpOHTeJihCTBa, O6opy)].OBaHIDI H ,n:pyrttx rpy30B, "
    "Heo6XO)].HMhIX ):(JI.SI BhmOJTHeHHR pa6oT no ,[(orosopy reHTTO,npH,na"
)

NORMAL_RU = (
    "Подрядчик обязуется выполнить строительно-монтажные работы в срок, установленный "
    "графиком производства работ. За нарушение срока Заказчик вправе начислить неустойку "
    "в размере ноль целых одна десятая процента от стоимости этапа за каждый день "
    "просрочки, но не более десяти процентов цены Договора и приложений к нему."
)

NORMAL_EN = (
    "The Contractor shall complete the Works by the date set out in the Programme. "
    "Liquidated damages shall accrue at zero point one per cent of the Contract Price per "
    "day of delay, capped at ten per cent of the Contract Price and its annexes hereto."
)

NORMAL_CAPS = (
    "ДОГОВОР ГЕНЕРАЛЬНОГО ПОДРЯДА НА ВЫПОЛНЕНИЕ СТРОИТЕЛЬНО-МОНТАЖНЫХ РАБОТ. "
    "ПРИЛОЖЕНИЕ НОМЕР ДВА. СТРУКТУРА ЦЕНЫ ДОГОВОРА. АКТ ПРИЕМКИ ЗАКОНЧЕННОГО "
    "СТРОИТЕЛЬСТВОМ ОБЪЕКТА. ВЕДОМОСТЬ ОБЪЕМОВ РАБОТ И СМЕТНАЯ ДОКУМЕНТАЦИЯ СТОРОН."
)


def test_broken_encoding_is_rejected():
    v = assess_extracted_text(BROKEN)
    assert v.ok is False
    assert v.reason == "broken_encoding"
    assert v.message == BROKEN_ENCODING_MESSAGE


@pytest.mark.parametrize("sample", [NORMAL_RU, NORMAL_EN, NORMAL_CAPS])
def test_readable_text_passes(sample):
    v = assess_extracted_text(sample)
    assert v.ok is True
    assert v.reason == ""


def test_english_document_is_not_punished_for_absent_cyrillic():
    """Критерий языконезависимый: англоязычный договор — валидный документ."""
    v = assess_extracted_text(NORMAL_EN)
    assert v.ok is True
    assert v.cyrillic_share == 0.0


def test_short_text_is_not_judged():
    """На коротком фрагменте признак шумит — не бракуем."""
    short = "СНиП ГОСТ КСиП"
    assert len(short) < MIN_LETTERS_TO_JUDGE
    assert assess_extracted_text(short).ok is True


def test_abbreviations_alone_do_not_break_a_real_document():
    """«СНиП» задевает признак, но на документе целиком его доля мала."""
    text = NORMAL_RU + " Работы ведутся по СНиП 3.03.01-87 и СНиП 12-03-2001."
    assert assess_extracted_text(text).ok is True


@pytest.mark.parametrize("empty", ["", None, "   "])
def test_empty_input_is_safe(empty):
    v = assess_extracted_text(empty)
    assert v.ok is True and v.letters == 0


def test_metrics_are_reported_for_logs():
    v = assess_extracted_text(BROKEN)
    assert v.letters > 0
    assert v.mixed_case_share > 0.5
    assert v.cyrillic_share == 0.0


def test_mixed_case_metric_separates_broken_from_normal():
    assert mixed_case_word_share(BROKEN) > 0.5
    assert mixed_case_word_share(NORMAL_RU) == 0.0
    assert mixed_case_word_share(NORMAL_CAPS) == 0.0


def test_cyrillic_share_is_diagnostic_only():
    assert cyrillic_share(NORMAL_RU) == 1.0
    assert cyrillic_share(BROKEN) == 0.0
