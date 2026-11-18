"""Private SSH protocol for importing object documents through presigned S3."""

import argparse
import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import select, text

from ..api.documents import create_s3_document_upload, confirm_s3_document_upload
from ..database import async_session, engine
from ..models import DocumentRecord, TenderHubRegistryLink, User
from ..schemas.document import DocumentUploadSessionRequest
from ..services import document_storage


async def prepare(entries: list[dict], owner_id: int) -> list[dict]:
    # The session lock survives upload-session commits and serializes retrying clients.
    async with engine.connect() as lock:
        await lock.execute(text("SELECT pg_advisory_lock(hashtext('meridian-context-import'))"))
        try:
            async with async_session() as db:
                user = await db.get(User, owner_id)
                if user is None or not user.is_active or user.role != "admin":
                    raise ValueError("An active Meridian administrator is required")
                links = {
                    row.registry_id: row.object_id
                    for row in (await db.scalars(select(TenderHubRegistryLink))).all()
                }
                documents = (await db.scalars(select(DocumentRecord).where(
                    DocumentRecord.object_id.in_(set(links.values())),
                    DocumentRecord.status != "deleted",
                ))).all()
                existing = {}
                for doc in documents:
                    source = (doc.doc_meta or {}).get("import_source")
                    if isinstance(source, dict):
                        existing[(doc.object_id, source.get("key"), source.get("sha256"))] = doc
                results = []
                for entry in entries:
                    registry_id = str(UUID(entry["registry_id"]))
                    object_id = links.get(registry_id)
                    if object_id is None:
                        raise ValueError("Registry row has no Meridian object")
                    source = entry["source"]
                    identity = (object_id, source["key"], source["sha256"])
                    doc = existing.get(identity)
                    if doc is None:
                        upload = await create_s3_document_upload(
                            db, user,
                            DocumentUploadSessionRequest(
                                filename=entry["filename"], content_type=entry["content_type"],
                                size_bytes=entry["size"], object_id=object_id,
                            ),
                            meeting_id=None, import_source=source,
                        )
                        doc = await db.get(DocumentRecord, upload.document_id)
                        existing[identity] = doc
                        result = {
                            "uid": entry["uid"], "document_id": doc.id,
                            "status": "pending", "upload_url": upload.upload_url,
                            "headers": upload.headers,
                        }
                    elif doc.status == "pending":
                        url, headers = document_storage.create_presigned_put(doc.s3_key, doc.mime_type)
                        result = {
                            "uid": entry["uid"], "document_id": doc.id,
                            "status": doc.status, "upload_url": url, "headers": headers,
                        }
                    else:
                        result = {"uid": entry["uid"], "document_id": doc.id, "status": doc.status}
                    results.append(result)
                return results
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(hashtext('meridian-context-import'))"))


async def confirm(document_ids: list[int], owner_id: int) -> list[dict]:
    results = []
    async with async_session() as db:
        user = await db.get(User, owner_id)
        if user is None or not user.is_active or user.role != "admin":
            raise ValueError("An active Meridian administrator is required")
        for document_id in document_ids:
            doc = (await db.scalars(select(DocumentRecord).where(
                DocumentRecord.id == document_id,
            ).with_for_update())).one_or_none()
            if doc is None or doc.created_by_user_id != owner_id:
                raise ValueError("Imported document does not belong to this user")
            if doc.status == "pending":
                doc = await confirm_s3_document_upload(db, user, document_id, meeting_id=None)
            results.append({"document_id": doc.id, "status": doc.status})
    return results


async def run(action: str, payload: list, owner_id: int) -> list[dict]:
    try:
        if action == "prepare":
            return await prepare(payload, owner_id)
        return await confirm(payload, owner_id)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "confirm"))
    parser.add_argument("--owner-user-id", type=int, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.action, json.load(sys.stdin), args.owner_user_id))
    except Exception as error:
        # stdout is a private client protocol and may contain upload signatures on success.
        # Errors contain only the exception class, never URLs or credentials.
        parser.exit(2, f"Context import failed ({type(error).__name__}).\n")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
