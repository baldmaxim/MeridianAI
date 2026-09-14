# -*- coding: utf-8 -*-
"""HTML-вёрстка chandra-ocr-2 → чистый текст для поиска по договору.

Формат взят с реальных страниц договора: модель отдаёт блоки с координатами и метками.
Слова div/bbox/label и числа координат в поиске совпадали бы с чем угодно.
"""

from app.services.ocr_text import ocr_markup_to_text

PAGE = (
    '<div data-bbox="462 61 608 77" data-label="Section-Header"><h2>1. Терминология</h2></div>'
    '<div data-bbox="207 105 697 123" data-label="Text"><p>В настоящем Договоре, если контекст '
    'не предполагает иного:</p></div>'
    '<div data-bbox="148 129 930 345" data-label="List-Group"><ul style="list-style-type: none;">'
    '<li>- слова, означающие единственное число, означают множественное;</li>'
    '<li>• ссылки на закон означают ссылки на закон в измененной форме.</li></ul></div>'
)

TABLE = (
    '<div data-bbox="1 2 3 4" data-label="Table"><table><thead><tr><th>Этап</th><th>Срок</th>'
    '<th>Сумма, руб.</th></tr></thead><tbody><tr><td>Монолит</td><td>30 мес.</td>'
    '<td>1&nbsp;250&nbsp;000</td></tr></tbody></table></div>'
)


def test_layout_markup_is_removed():
    text = ocr_markup_to_text(PAGE)
    for junk in ("<", "bbox", "data-label", "List-Group", "462"):
        assert junk not in text


def test_structure_survives():
    lines = ocr_markup_to_text(PAGE).split("\n")
    assert lines[0] == "1. Терминология"
    assert lines[1] == "В настоящем Договоре, если контекст не предполагает иного:"
    assert lines[2] == "- слова, означающие единственное число, означают множественное;"


def test_bullet_is_not_doubled():
    """Модель ставит тире внутри пункта списка — «- - слова» не нужно."""
    text = ocr_markup_to_text(PAGE)
    assert "- -" not in text and "- •" not in text
    assert "- ссылки на закон" in text


def test_table_rows_keep_cells_apart():
    lines = ocr_markup_to_text(TABLE).split("\n")
    assert "Этап | Срок | Сумма, руб." in lines
    assert any(line.startswith("Монолит | 30 мес. | 1") and "250" in line for line in lines)


def test_plain_text_and_markdown_pass_through():
    md = "# ДОГОВОР\n\n| Этап | Срок |\n|---|---|\n| Монолит | 30 мес. |"
    assert ocr_markup_to_text(md) == md


def test_entities_are_decoded():
    assert ocr_markup_to_text("<p>ООО &laquo;Балчуг&raquo; &amp; партнёры</p>") == "ООО «Балчуг» & партнёры"


def test_layout_json_is_dropped():
    """Реальный случай со стр. 53 договора: вместо текста — служебный список блоков."""
    raw = ('[{"label": "Text", "bbox": "149 57 926 96"}, {"label": "List-Group", "bbox": "208 103 887 366"}]'
           '<div data-bbox="1 2 3 4" data-label="Text"><p>13.2. Оплата производится ежемесячно.</p></div>')
    text = ocr_markup_to_text(raw)
    assert text == "13.2. Оплата производится ежемесячно."


def test_brackets_in_contract_text_survive():
    assert ocr_markup_to_text("<p>Срок [в календарных днях] — 30</p>") == "Срок [в календарных днях] — 30"


def test_empty_input():
    assert ocr_markup_to_text(None) == ""
    assert ocr_markup_to_text('<div data-bbox="1 1 1 1" data-label="Picture"><img src="x"/></div>') == ""
