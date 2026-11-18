"""Upload a local source manifest directly to S3, with private SSH metadata calls."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import requests


def remote_call(host: str, container: str, action: str, owner_id: int, payload: list) -> list[dict]:
    command = (
        f"docker exec -i {container} python -m app.tools.import_context_files "
        f"{action} --owner-user-id {owner_id}"
    )
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
        input=json.dumps(payload, ensure_ascii=True), text=True,
        capture_output=True, timeout=180,
    )
    if result.returncode:
        raise RuntimeError(f"Remote import command failed (exit {result.returncode})")
    return json.loads(result.stdout)


def put_file(entry: dict, upload: dict) -> dict:
    path = Path(entry["path"])
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != entry["file_sha256"] or path.stat().st_size != entry["size"]:
        return {"uid": entry["uid"], "status": "source_changed"}
    for attempt in range(3):
        try:
            with path.open("rb") as source:
                response = requests.put(upload["upload_url"], headers=upload["headers"],
                                        data=source, timeout=(15, 120))
            if 200 <= response.status_code < 300:
                return {"uid": entry["uid"], "status": "put", "document_id": upload["document_id"]}
            failure = f"S3 HTTP {response.status_code}"
        except requests.RequestException as error:
            failure = type(error).__name__
        if attempt < 2:
            time.sleep(attempt + 1)
    return {"uid": entry["uid"], "status": "upload_failed", "error": failure}


def sync(entries: list[dict], host: str, container: str, owner_id: int, checkpoint: Path) -> dict:
    results = {}
    for offset in range(0, len(entries), 25):
        batch = entries[offset:offset + 25]
        metadata = [{key: value for key, value in entry.items()
                     if key not in {"path", "file_sha256"}} for entry in batch]
        prepared = remote_call(host, container, "prepare", owner_id, metadata)
        by_uid = {entry["uid"]: entry for entry in batch}
        pending = [upload for upload in prepared if upload["status"] == "pending"]
        for item in prepared:
            if item["status"] != "pending":
                results[item["uid"]] = item
        with ThreadPoolExecutor(max_workers=4) as pool:
            uploaded = list(pool.map(lambda upload: put_file(by_uid[upload["uid"]], upload), pending))
        ids = [item["document_id"] for item in uploaded if item["status"] == "put"]
        confirmed = remote_call(host, container, "confirm", owner_id, ids) if ids else []
        statuses = {item["document_id"]: item["status"] for item in confirmed}
        for item in uploaded:
            if item["status"] == "put":
                item["status"] = statuses[item["document_id"]]
            results[item["uid"]] = item
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps({"results": list(results.values())}, indent=2), encoding="utf-8")
        temporary.replace(checkpoint)
        print(json.dumps({"handled": min(offset + 25, len(entries)), "total": len(entries),
                          "failed": sum(item["status"] in {"upload_failed", "source_changed", "error"}
                                        for item in results.values())}), flush=True)
    return {"results": list(results.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--container", default="meridian-api-1")
    parser.add_argument("--owner-user-id", type=int, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.container):
        parser.error("Invalid container name")
    if args.ssh_host.startswith("-"):
        parser.error("Invalid SSH host")
    try:
        entries = json.loads(args.manifest.read_text(encoding="utf-8-sig"))["entries"]
        report = sync(entries, args.ssh_host, args.container, args.owner_user_id, args.checkpoint)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"Context sync failed ({type(error).__name__}).\n")
    if any(item["status"] in {"upload_failed", "source_changed", "error"} for item in report["results"]):
        parser.exit(1, "Some documents require a retry.\n")


if __name__ == "__main__":
    main()
