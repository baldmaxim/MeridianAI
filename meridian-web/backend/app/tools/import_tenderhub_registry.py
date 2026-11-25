"""Preview or apply a TenderHub registry snapshot to Meridian."""

import argparse
import asyncio
from collections import Counter, defaultdict
from collections.abc import Iterator
import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, StringConstraints, TypeAdapter, ValidationError
from sqlalchemy import select, text

from ..api.objects import resolve_or_create_customer
from ..database import async_session
from ..models import ProjectObject, TenderHubRegistryLink, User


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
ACTIVE_STATUSES = {"calc", "sent", "waiting_pd"}


class RegistryReference(BaseModel):
    name: str


class RegistryRow(BaseModel):
    id: UUID
    title: Name
    client_name: Name
    tender_number: str | None = None
    object_address: Address | None = None
    dashboard_status: str | None = None
    status: RegistryReference | None = None
    construction_scope: RegistryReference | None = None
    area: float | None = None
    is_archived: bool
    submission_date: str | None = None
    updated_at: str | None = None

    @property
    def is_tender_won(self) -> bool:
        # Сырой статус реестра: effective_status для «Выиграл» уже «archive».
        return bool(self.status) and "выиграл" in self.status.name.casefold()

    @property
    def effective_status(self) -> str:
        if self.is_archived:
            return "archive"
        # Use the registry UI's status-name precedence, including legacy rows.
        name = self.status.name.strip().casefold() if self.status else ""
        if "выиграл" in name or "проиграл" in name:
            return "archive"
        if name == "в работе":
            return "calc"
        if name == "направлено":
            return "sent"
        if "ожида" in name:
            return "waiting_pd"
        return self.dashboard_status or "calc"


class RegistrySnapshot(BaseModel):
    data: list[RegistryRow]


def plan_import(
    rows: list[RegistryRow], links: dict[str, int], objects: dict[int, ProjectObject],
    overrides: dict[UUID, int], create_ids: set[UUID] | None = None,
) -> Iterator[tuple[RegistryRow, str, int | None, list[int]]]:
    numbers = Counter(
        (row.tender_number or "").strip().casefold()
        for row in rows if row.effective_status != "archive"
    )
    names: dict[str, list[int]] = defaultdict(list)
    for obj in objects.values():
        names[obj.name.strip().casefold()].append(obj.id)
    source_names = Counter(
        row.title.casefold() for row in rows
        if row.effective_status in ACTIVE_STATUSES
    )

    for row in rows:
        registry_id = str(row.id)
        linked_id = links.get(registry_id)
        override = overrides.get(row.id)
        candidates = names[row.title.casefold()]
        number = (row.tender_number or "").strip().casefold()
        if override is not None and (override not in objects or linked_id not in (None, override)):
            yield row, "invalid_mapping", override, []
        elif linked_id is not None:
            yield row, "refresh", linked_id, []
        elif row.effective_status == "archive":
            yield row, "archived", None, []
        elif row.effective_status not in ACTIVE_STATUSES:
            yield row, "review_status", None, []
        elif override is not None:
            yield row, "link", override, []
        elif candidates or numbers[number] > 1 or source_names[row.title.casefold()] > 1 or not number:
            yield row, "review_match", None, candidates
        elif create_ids is not None and row.id not in create_ids:
            yield row, "review_create", None, []
        else:
            yield row, "create", None, []


async def import_registry(
    rows: list[RegistryRow], overrides: dict[UUID, int], owner_id: int | None,
    create_ids: set[UUID] | None = None,
) -> dict:
    async with async_session.begin() as db:
        if owner_id is None:
            await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        else:
            # Serialize applies so a second run sees the first run's objects and links.
            await db.execute(text("LOCK TABLE tenderhub_registry_links IN SHARE ROW EXCLUSIVE MODE"))
            if await db.get(User, owner_id) is None:
                raise ValueError("The Meridian owner user does not exist.")
            if create_ids is None:
                create_ids = set()

        objects = {obj.id: obj for obj in (await db.scalars(select(ProjectObject))).all()}
        stored = {
            link.registry_id: link
            for link in (await db.scalars(select(TenderHubRegistryLink))).all()
        }
        links = {key: value.object_id for key, value in stored.items()}
        plan = list(plan_import(rows, links, objects, overrides, create_ids))
        if owner_id is not None and any(action == "invalid_mapping" for _, action, _, _ in plan):
            raise ValueError("At least one mapping references a missing object or conflicts with an existing link.")

        report = []
        for row, action, object_id, candidates in plan:
            registry_id = str(row.id)
            item = {
                "registry_id": registry_id,
                "number": row.tender_number,
                "title": row.title,
                "customer": row.client_name,
                "status": row.effective_status,
                "action": action,
                "object_id": object_id,
                "candidate_object_ids": candidates,
            }
            report.append(item)
            if owner_id is None or action not in {"create", "link", "refresh"}:
                continue

            data = row.model_dump(mode="json", exclude={"id"})
            data["effective_status"] = row.effective_status
            if action == "create":
                customer = await resolve_or_create_customer(db, owner_id, row.client_name)
                obj = ProjectObject(
                    owner_user_id=owner_id, customer_id=customer.id,
                    name=row.title, address=row.object_address or None,
                )
                db.add(obj)
                await db.flush()
                object_id = item["object_id"] = obj.id
            if action in {"link", "refresh"} and row.is_tender_won:
                linked = objects.get(object_id)
                if linked is not None:
                    linked.tender_won = True  # только True, обратно не сбрасываем
            if action == "refresh":
                stored[registry_id].registry_data = data
            else:
                db.add(TenderHubRegistryLink(registry_id=registry_id, object_id=object_id, registry_data=data))

    return {
        "mode": "preview" if owner_id is None else "apply",
        "counts": dict(Counter(item["action"] for item in report)),
        "rows": report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="UTF-8 JSON response from GET /api/v1/tender-registry/export")
    parser.add_argument("--links", type=Path, help="JSON object mapping registry UUIDs to Meridian object IDs")
    parser.add_argument("--create-list", type=Path, help="JSON array of registry UUIDs approved for card creation")
    parser.add_argument("--apply", action="store_true", help="Persist links, refreshes and approved creations. The default is preview.")
    parser.add_argument("--owner-user-id", type=int, help="Meridian user credited for newly created cards")
    args = parser.parse_args()
    if args.apply != (args.owner_user_id is not None):
        parser.error("--apply and --owner-user-id must be provided together")

    try:
        rows = RegistrySnapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8-sig")).data
        overrides = (
            TypeAdapter(dict[UUID, int]).validate_json(args.links.read_text(encoding="utf-8-sig"))
            if args.links else {}
        )
        create_ids = (
            TypeAdapter(set[UUID]).validate_json(args.create_list.read_text(encoding="utf-8-sig"))
            if args.create_list else None
        )
        row_ids = {row.id for row in rows}
        if len(row_ids) != len(rows):
            raise ValueError("Snapshot has duplicate registry IDs.")
        if not overrides.keys() <= row_ids or not (create_ids or set()) <= row_ids:
            raise ValueError("A link or approval references a registry ID absent from the snapshot.")
        if create_ids and not create_ids.isdisjoint(overrides):
            raise ValueError("A registry ID cannot be approved for creation and mapped to an existing object.")
        report = asyncio.run(import_registry(rows, overrides, args.owner_user_id, create_ids))
    except ValidationError as exc:
        parser.exit(2, f"Invalid snapshot, mapping or approval list ({exc.error_count()} validation errors).\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
