from app.services.document_names import document_display_name


def test_ocr_result_prefix_and_suffix_removed():
    name = "Документация OCR 343 · файл 1980-01-01 · 01-09-01-06-08-ИНПИ.2025.21-П-ПБ1.3_results.md"
    assert document_display_name(name) == "01-09-01-06-08-ИНПИ.2025.21-П-ПБ1.3"


def test_offer_prefix_removed_extension_kept():
    name = "КП 343 · 2026-11-09 · 001 Отправка 09.11.2026 · Приложение №5. Смета.docx"
    assert document_display_name(name) == "Приложение №5. Смета.docx"


def test_without_separator_returned_as_is():
    assert document_display_name("Договор.pdf") == "Договор.pdf"


def test_results_suffix_variants():
    assert document_display_name("Скан_results") == "Скан"
    assert document_display_name("Заметки.md") == "Заметки"


def test_empty_inputs_fall_back_to_original():
    assert document_display_name("") == ""
    assert document_display_name("КП 1 · 2026-01-01 · ") == "КП 1 · 2026-01-01 · "
    assert document_display_name("a · _results.md") == "a · _results.md"
