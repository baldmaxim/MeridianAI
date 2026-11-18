import hashlib
import json
from types import SimpleNamespace
import zipfile

from app.tools import sync_context_files as syncer
from app.tools.prepare_context_sources import stage


def test_retry_uses_existing_documents_and_keeps_upload_signatures_out_of_checkpoint(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"offer contents")
    entry = {"uid": "entry", "path": str(source), "size": source.stat().st_size,
             "file_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    checkpoint = tmp_path / "checkpoint.json"
    upload_url = "https://storage.example.test/file?signature=private"
    puts = []
    confirmed = False

    def remote(host, container, action, owner_id, payload):
        nonlocal confirmed
        if action == "confirm":
            confirmed = True
            assert payload == [42]
            return [{"document_id": 42, "status": "uploaded"}]
        if confirmed:
            return [{"uid": "entry", "document_id": 42, "status": "ready"}]
        return [{"uid": "entry", "document_id": 42, "status": "pending",
                 "upload_url": upload_url, "headers": {}}]

    def put(url, **kwargs):
        puts.append(kwargs["data"].read())
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(syncer, "remote_call", remote)
    monkeypatch.setattr(syncer.requests, "put", put)
    syncer.sync([entry], "host", "container", 11, checkpoint)
    syncer.sync([entry], "host", "container", 11, checkpoint)

    assert puts == [b"offer contents"]
    assert json.loads(checkpoint.read_text())["results"] == [
        {"uid": "entry", "document_id": 42, "status": "ready"},
    ]
    assert "signature" not in checkpoint.read_text()


def test_submission_history_keeps_dates_and_skips_archive_copy_of_same_submission(tmp_path):
    root = tmp_path / "share"
    rows = []
    for submission in ("001 01.02.2026", "002 02.02.2026"):
        path = root / "321. Project" / "3. Отправка КП" / submission / "offer.txt"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"same content in two submissions")
        rows.append({"number": "321", "role": "offer", "relative_path": str(path.relative_to(root)),
                     "ext": ".txt", "mtime_ns": path.stat().st_mtime_ns})
    archive = root / "321. Project" / "3. Отправка КП" / "001 01.02.2026" / "package.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("offer.txt", b"same content in two submissions")
    rows.append({"number": "321", "role": "offer", "relative_path": str(archive.relative_to(root)),
                 "ext": ".zip", "mtime_ns": archive.stat().st_mtime_ns})
    broken = archive.with_name("broken.zip")
    broken.write_bytes(b"broken archive")
    rows.append({"number": "321", "role": "offer", "relative_path": str(broken.relative_to(root)),
                 "ext": ".zip", "mtime_ns": broken.stat().st_mtime_ns})
    calculations = tmp_path / "calculations.json"
    calculations.write_text('{"entries": []}')
    registry = {"data": [{"id": "registry", "tender_number": "321", "is_archived": False}]}

    result = stage({"root": str(root), "entries": rows}, registry, calculations, tmp_path / "out", None)

    assert len(result["entries"]) == 2
    assert len({entry["uid"] for entry in result["entries"]}) == 2
    assert {entry["source"]["date"] for entry in result["entries"]} == {"2026-02-01", "2026-02-02"}
    assert all(entry["source"]["date"] in entry["filename"] for entry in result["entries"])
    assert [entry["reason"] for entry in result["skipped"]] == ["archive_duplicate", "archive_unreadable"]
