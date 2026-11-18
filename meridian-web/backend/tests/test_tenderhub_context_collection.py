from decimal import Decimal

import pytest

from app.tools.collect_tenderhub_context import render_calculation, select_calculation


def test_latest_calculation_is_selected_by_number_and_customer():
    row = {"tender_number": "321.4", "client_name": "Заказчик"}
    calculations = [
        {"id": "older", "tender_number": "321.4", "client_name": "Заказчик", "version": 2},
        {"id": "latest", "tender_number": "321.4", "client_name": "ЗАКАЗЧИК ", "version": 3},
        {"id": "other-lot", "tender_number": "321", "client_name": "Заказчик", "version": 7},
        {"id": "other-customer", "tender_number": "321.4", "client_name": "Другой", "version": 8},
    ]
    assert select_calculation(row, calculations)["id"] == "latest"
    assert select_calculation({**row, "tender_number": "absent"}, calculations) is None


def test_duplicate_latest_versions_require_explicit_resolution():
    row = {"tender_number": "1", "client_name": "Заказчик"}
    candidates = [{**row, "id": identifier, "version": 1} for identifier in ("one", "two")]
    with pytest.raises(ValueError, match="same latest version"):
        select_calculation(row, candidates)


def test_calculation_document_preserves_source_totals_precision_and_archive_state():
    row = {"id": "registry", "tender_number": "1", "title": "Объект", "dashboard_status": "sent"}
    calculation = {"id": "calculation", "version": 3, "is_archived": True}
    overview = {"title": "Объект", "client_name": "Заказчик", "cached_grand_total": Decimal("123456789.12345")}
    positions = [{"id": "position", "position_number": 1, "work_name": "Работы", "commercial_total": Decimal("0.00")}]

    document = render_calculation(row, calculation, overview, positions, "https://example.test", "2026-01-01")

    assert "123456789.12345" in document
    assert "commercial_total): 0.00" in document
    assert "Версия расчёта: 3" in document
    assert "Карточка расчёта архивная: да" in document
    assert "UUID строки реестра: registry" in document
