from types import SimpleNamespace
from uuid import UUID

from app.tools.import_tenderhub_registry import RegistryRow, plan_import


def row(index, **fields):
    return RegistryRow.model_validate({
        "id": str(UUID(int=index)),
        "tender_number": str(index),
        "title": f"Объект {index}",
        "client_name": "Заказчик",
        "is_archived": False,
        **fields,
    })


def test_preview_uses_registry_status_and_requires_resolution_for_ambiguous_objects():
    rows = [
        row(1),
        row(2, status={"name": "Выиграли"}, dashboard_status="sent"),
        row(3, dashboard_status="calc", is_archived=True),
        row(4, dashboard_status="waiting_pd"),
        row(5, tender_number="4", dashboard_status="sent"),
        row(6, title="Уже заведён"),
        row(7, dashboard_status="new_status"),
    ]
    objects = {12: SimpleNamespace(id=12, name="Уже заведён")}
    results = list(plan_import(rows, {}, objects, {}))
    assert [action for _, action, _, _ in results] == [
        "create", "archived", "archived", "review_match", "review_match", "review_match", "review_status",
    ]
    assert results[5][3] == [12]


def test_saved_link_prevents_duplicate_creation_and_cannot_be_reassigned_by_import():
    linked = row(1, title="Переименованный объект", is_archived=True)
    existing = row(2, title="Другой объект")
    objects = {key: SimpleNamespace(id=key, name=f"Объект {key}") for key in (12, 34)}
    links = {str(linked.id): 12}
    assert list(plan_import([linked, existing], links, objects, {existing.id: 12})) == [
        (linked, "refresh", 12, []),
        (existing, "link", 12, []),
    ]
    assert list(plan_import([linked], links, objects, {linked.id: 34})) == [
        (linked, "invalid_mapping", 34, []),
    ]


def test_create_list_defers_unreviewed_rows_and_keeps_match_checks():
    approved, unreviewed, matched, linked = row(1), row(2), row(3), row(4)
    rows = [approved, unreviewed, matched, linked]
    objects = {12: SimpleNamespace(id=12, name=matched.title)}
    links = {str(linked.id): 12}

    assert list(plan_import(rows, links, objects, {}, {approved.id, matched.id})) == [
        (approved, "create", None, []),
        (unreviewed, "review_create", None, []),
        (matched, "review_match", None, [12]),
        (linked, "refresh", 12, []),
    ]
    assert list(plan_import([approved], {}, {}, {}, set())) == [
        (approved, "review_create", None, []),
    ]


def test_won_status_marks_tender_won_even_though_effective_status_is_archive():
    won = row(1, status={"name": "Выиграл тендер"})
    lost = row(2, status={"name": "Проиграл"})
    work = row(3, status={"name": "В работе"})
    assert won.effective_status == "archive"
    assert won.is_tender_won is True
    assert lost.is_tender_won is False
    assert work.is_tender_won is False
    assert row(4).is_tender_won is False


def test_linked_won_row_is_planned_as_refresh():
    won = row(1, status={"name": "выиграл"})
    objects = {12: SimpleNamespace(id=12, name="Объект 1")}
    plan = list(plan_import([won], {str(won.id): 12}, objects, {}))
    assert [(action, object_id) for _, action, object_id, _ in plan] == [("refresh", 12)]
    assert plan[0][0].is_tender_won
