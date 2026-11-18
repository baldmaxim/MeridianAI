"""Export versioned TenderHub calculations as documents for meeting context."""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import UUID

import requests


POSITION_FIELDS = (
    ("item_no", "Номер в ВОР"),
    ("unit_code", "Единица измерения"),
    ("volume", "Объём"),
    ("manual_volume", "Ручной объём"),
    ("material_cost_total", "Стоимость материалов"),
    ("work_cost_total", "Стоимость работ"),
    ("base_total", "Базовая стоимость позиции"),
    ("total_commercial_material", "Коммерческая стоимость материалов"),
    ("total_commercial_work", "Коммерческая стоимость работ"),
    ("commercial_total", "Коммерческая стоимость позиции"),
    ("material_cost_per_unit", "Материалы на единицу"),
    ("work_cost_per_unit", "Работы на единицу"),
    ("total_commercial_material_per_unit", "Коммерческие материалы на единицу"),
    ("total_commercial_work_per_unit", "Коммерческие работы на единицу"),
    ("markup_percentage", "Параметр наценки из API"),
    ("client_note", "Примечание заказчика"),
    ("manual_note", "Примечание расчёта"),
)


def fetch(session: requests.Session, base_url: str, route: str):
    response = session.get(base_url.rstrip("/") + route, timeout=(10, 60))
    if response.status_code != 200:
        raise ValueError(f"TenderHub HTTP {response.status_code}")
    return response.json(parse_float=Decimal)["data"], response.content


def select_calculation(row: dict, calculations: list[dict]) -> dict | None:
    candidates = [
        item for item in calculations
        if (item.get("tender_number") or "").strip().casefold()
        == (row.get("tender_number") or "").strip().casefold()
        and (item.get("client_name") or "").strip().casefold()
        == row["client_name"].strip().casefold()
    ]
    if not candidates:
        return None
    version = max(int(item["version"]) for item in candidates)
    latest = [item for item in candidates if int(item["version"]) == version]
    if len(latest) != 1:
        raise ValueError("Several calculation cards have the same latest version")
    return latest[0]


def render_calculation(row: dict, calculation: dict, overview: dict, positions: list[dict],
                       base_url: str, fetched_at: str) -> str:
    lines = [
        f"# Расчёт TenderHub — тендер № {row['tender_number']}",
        f"Объект реестра: {row['title']}",
        f"Объект в расчёте: {overview['title']}",
        f"Заказчик: {overview['client_name']}",
        f"Версия расчёта: {calculation['version']}",
        f"UUID расчёта: {calculation['id']}",
        f"UUID строки реестра: {row['id']}",
        "Выбор версии: наибольшая версия по номеру тендера и заказчику.",
        f"Карточка расчёта архивная: {'да' if calculation['is_archived'] else 'нет'}",
        f"Статус реестра: {row.get('dashboard_status') or ''}",
        f"Пакет работ в расчёте: {overview.get('construction_scope') or ''}",
        f"Обновление расчёта: {overview.get('updated_at') or ''}",
        f"Снимок получен (UTC): {fetched_at}",
        f"Источник: {base_url.rstrip('/')}/api/v1/tenders/{calculation['id']}/overview",
        "",
        "## Итог из TenderHub",
        f"cached_grand_total: {overview.get('cached_grand_total')}",
        f"Валюта: {overview.get('currency') or 'не указана в ответе API'}",
        f"Количество позиций: {len(positions)}",
        "",
    ]
    for position in positions:
        lines.extend([
            f"## Позиция {position['position_number']} — {position['work_name']}",
            f"UUID позиции: {position['id']}",
            f"Уровень раздела: {position.get('hierarchy_level')}",
        ])
        for key, label in POSITION_FIELDS:
            value = position.get(key)
            if value is not None and value != "":
                lines.append(f"{label} ({key}): {value}")
        lines.append("")
    return "\n".join(lines)


def collect(registry: dict, output: Path, base_url: str, session: requests.Session) -> dict:
    calculations, _ = fetch(session, base_url, "/api/v1/tenders/brief")
    fetched_at = datetime.now(timezone.utc).isoformat()
    entries = []
    for row in registry["data"]:
        if row["is_archived"] or row.get("dashboard_status") not in {"calc", "sent", "waiting_pd"}:
            continue
        entry = {"registry_id": str(UUID(row["id"])), "number": row["tender_number"]}
        try:
            calculation = select_calculation(row, calculations)
            if calculation is None:
                entry["status"] = "calculation_not_found"
                entries.append(entry)
                continue
            tender_id = str(UUID(calculation["id"]))
            route = f"/api/v1/tenders/{tender_id}"
            overview, overview_bytes = fetch(session, base_url, route + "/overview")
            positions, positions_bytes = fetch(session, base_url, route + "/positions/with-costs")
            if overview["id"] != tender_id or any(item["tender_id"] != tender_id for item in positions):
                raise ValueError("Calculation identifiers do not match")
            if int(overview["position_count"]) != len(positions):
                raise ValueError("Position count changed or the positions response is incomplete")
            scope = (row.get("construction_scope") or {}).get("name", "")
            entry.update({
                "tender_id": tender_id, "version": calculation["version"],
                "calculation_archived": calculation["is_archived"],
                "scope_matches_registry": scope.strip().casefold()
                == (overview.get("construction_scope") or "").strip().casefold(),
            })
            content = render_calculation(row, calculation, overview, positions, base_url, fetched_at)
            directory = output / entry["registry_id"]
            directory.mkdir(parents=True, exist_ok=True)
            number = re.sub(r"[^\w.-]", "_", row["tender_number"])
            filename = f"TenderHub-{number}-v{calculation['version']}.md"
            encoded = content.encode("utf-8")
            (directory / filename).write_bytes(encoded)
            (directory / "overview.json").write_bytes(overview_bytes)
            (directory / "positions.json").write_bytes(positions_bytes)
            entry.update({
                "status": "collected", "file": str(Path(entry["registry_id"]) / filename),
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "source_sha256": hashlib.sha256(overview_bytes + b"\n" + positions_bytes).hexdigest(),
                "positions": len(positions), "chars": len(content),
            })
        except (ValueError, KeyError, requests.RequestException) as error:
            entry.update({"status": "error", "error_type": type(error).__name__})
        entries.append(entry)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"fetched_at": fetched_at, "entries": entries}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.get("TENDERHUB_API_KEY")
    if not key:
        parser.error("TENDERHUB_API_KEY is required")
    registry = json.loads(args.registry.read_text(encoding="utf-8-sig"))
    with requests.Session() as session:
        session.headers["X-API-Key"] = key
        manifest = collect(registry, args.output, args.base_url, session)
    print(json.dumps({
        "collected": sum(entry["status"] == "collected" for entry in manifest["entries"]),
        "unresolved": [{"number": entry["number"], "status": entry["status"]}
                       for entry in manifest["entries"] if entry["status"] != "collected"],
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
