# -*- coding: utf-8 -*-
"""Нарезка договора по пунктам. Формат страниц — как у распознанного договора генподряда."""

from app.services.clause_chunker import chunk_by_clauses
from app.services.document_context import format_chunks_block


def _contract_pages() -> list[dict]:
    p72 = "\n".join(
        ["20. Ответственность Сторон"]
        + [f"20.7.1.{i}. Ключевое событие {i} – 100 000,00 руб. за каждый день просрочки." for i in range(1, 13)]
        + ["20.7.1.13. Получение ЗОС – 752 000,00 руб. за каждый день просрочки.",
           "При этом: - если срок получения ЗОС был соблюден, все ранее взысканные Застройщиком с", "72"])
    p73 = "\n".join(["73", "Генподрядчика неустойки подлежат возврату в течение 10 рабочих дней."])
    p57 = "\n".join(["13.2.1 Гарантийное удержание будет составлять 3% (три процента).",
                     "13.2.2 Застроитель ежемесячно удерживает 3% от стоимости Работ."])
    return [{"text": p72, "page_number": 72, "sheet_name": None},
            {"text": p73, "page_number": 73, "sheet_name": None},
            {"text": p57, "page_number": 57, "sheet_name": None}]


def test_clause_is_not_cut_at_page_break_and_page_numbers_dropped():
    rows = chunk_by_clauses(_contract_pages(), target_chars=400)
    zos = next(r for r in rows if "20.7.1.13" in r["clauses"])
    assert "все ранее взысканные Застройщиком с\nГенподрядчика неустойки подлежат возврату" in zos["text"]
    assert zos["page"] == 72 and zos["last_page"] == 73
    assert "\n72\n" not in zos["text"] and "\n73\n" not in zos["text"]


def test_section_heading_sticks_to_first_clause():
    rows = chunk_by_clauses(_contract_pages(), target_chars=400)
    assert rows[0]["text"].startswith("20. Ответственность Сторон\n20.7.1.1.")
    assert all(len(r["text"]) > 40 for r in rows)


def test_clause_without_recognized_heading_not_attributed_to_previous_section():
    rows = chunk_by_clauses(_contract_pages(), target_chars=400)
    retention = next(r for r in rows if "13.2.1" in r["clauses"])
    assert retention["section"] == "Раздел 13"
    assert retention["clauses"] == ["13.2.1", "13.2.2"]


def test_long_unnumbered_section_keeps_pages():
    terms = [{"text": "1. Терминология\n" + "\n".join(f"Термин {i} – определение термина номер {i}." * 3
                                                    for i in range(40)), "page_number": 3, "sheet_name": None},
             {"text": "\n".join(f"Термин {i} – определение термина номер {i}." * 3 for i in range(40, 80)),
              "page_number": 4, "sheet_name": None}]
    rows = chunk_by_clauses(terms + _contract_pages(), target_chars=1500, max_unit_chars=3000)
    term_rows = [r for r in rows if r["section"] == "1. Терминология"]
    assert len(term_rows) > 2 and max(len(r["text"]) for r in term_rows) <= 1500
    assert {r["page"] for r in term_rows} == {3, 4}


def test_letter_without_clauses_falls_back():
    letter = [{"text": "Уважаемый Иван Иванович!\nПросим согласовать перенос сроков.\n1. Первое\n2. Второе",
               "page_number": 1, "sheet_name": None}]
    assert chunk_by_clauses(letter) is None


def test_prompt_header_shows_section_and_clauses():
    block = format_chunks_block([{
        "document_name": "Договор.pdf", "page_number": 57, "section_title": "Раздел 13",
        "clauses": ["13.2.1", "13.2.2", "13.2.3"], "text": "13.2.1 Гарантийное удержание 3%.",
    }], 10, 14000)
    assert "[Документ: Договор.pdf | Страница 57 | Раздел 13 | Пункты 13.2.1–13.2.3]" in block
