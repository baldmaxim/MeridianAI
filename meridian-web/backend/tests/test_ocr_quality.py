# -*- coding: utf-8 -*-
"""Подозрительные страницы распознанного скана. Случаи взяты из договора генподряда."""

from app.services.ocr_quality import ocr_page_warnings, ocr_quality_note


def _p(n, text):
    return {"page_number": n, "text": text, "sheet_name": None}


BODY = "Генеральный подрядчик выполняет Работы в соответствии с Рабочей документацией. " * 30


def test_missing_page_is_reported():
    """Модель вернула пустоту на стр. 74 — такой страницы нет среди текста."""
    segs = [_p(73, BODY + "\n- если срок получения ЗОС был соблюден, все ранее взысканные Застройщиком с"),
            _p(75, BODY)]
    warnings = ocr_page_warnings(segs, page_count=75)
    assert {"page": 74, "reason": "страница не распознана"} in warnings
    assert ocr_quality_note(warnings).startswith("Сверьте со сканом стр. 1, 2, 3, 4, 5 …")


def test_capitalized_term_after_page_break_is_not_suspicious():
    """Термины договора пишутся с заглавной: «…после предоставления / Генподрядчиком…» — это не обрыв."""
    segs = [_p(1, BODY + "\nоплата производится сразу после предоставления"),
            _p(2, "Генподрядчиком подписанного Договора страхования.\n" + BODY),
            _p(3, BODY + "\nв связи с ввозом в"), _p(4, "Российскую Федерацию Материалов.\n" + BODY)]
    assert ocr_page_warnings(segs, page_count=4) == []


def test_phrase_cut_before_new_clause_is_suspicious():
    segs = [_p(1, BODY + "\nвсе ранее взысканные Застройщиком с"), _p(2, "20.8. Застроитель вправе.\n" + BODY)]
    warnings = ocr_page_warnings(segs, page_count=2)
    assert warnings == [{"page": 2, "reason": "фраза на стр. 1 обрывается перед новым пунктом — возможно, потерян текст"}]


def test_short_middle_page_reported_but_title_and_signatures_are_not():
    segs = [_p(1, "ДОГОВОР №1"), _p(2, BODY), _p(3, BODY), _p(4, "Приложение"), _p(5, BODY),
            _p(6, BODY), _p(7, "Подписи")]
    assert [w["page"] for w in ocr_page_warnings(segs, page_count=7)] == [4]


def test_clean_scan_has_no_note():
    assert ocr_quality_note(ocr_page_warnings([_p(1, BODY), _p(2, BODY)], page_count=2)) is None
