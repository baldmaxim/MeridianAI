"""Stage submission history, recognized documents and TenderHub calculation exports."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import io
import json
import mimetypes
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import zipfile


SUPPORTED = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".csv"}
CONVERT = {".doc": ".docx", ".pptx": ".pdf"}
DATE = re.compile(r"(?<!\d)(\d{2})[.](\d{2})[.](\d{4}|\d{2})(?!\d)")


def display_date(value: str, modified: int) -> tuple[str, str]:
    match = DATE.search(value)
    if match:
        day, month, year = match.groups()
        year = int(year) + (2000 if len(year) == 2 else 0)
        return datetime(year, int(month), int(day)).strftime("%Y-%m-%d"), "submission_name"
    return datetime.fromtimestamp(modified / 1_000_000_000).strftime("%Y-%m-%d"), "file_modified"


def stage(manifest: dict, registry: dict, calculation_manifest: Path, output: Path,
          office_binary: str | None) -> dict:
    active = {row["tender_number"]: row for row in registry["data"] if not row["is_archived"]}
    root = Path(manifest["root"])
    assets = output / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    entries, skipped = [], []
    direct_hashes = set()
    profile = (output / "office-profile").resolve().as_uri()

    def add(item: dict, raw: bytes, original_path: str, original_name: str,
            submission: str, *, archive: bool = False) -> None:
        number, role = item["number"], item["role"]
        row = active.get(number)
        if row is None:
            return
        ext = Path(original_name).suffix.casefold()
        if ext not in SUPPORTED | CONVERT.keys():
            skipped.append({"number": number, "path": original_path, "reason": "unsupported_format"})
            return
        digest = hashlib.sha256(raw).hexdigest()
        duplicate_key = (number, submission, digest)
        if archive and duplicate_key in direct_hashes:
            skipped.append({"number": number, "path": original_path, "reason": "archive_duplicate"})
            return
        direct_hashes.add(duplicate_key)
        path = assets / (digest + ext)
        if not path.exists():
            path.write_bytes(raw)
        original_digest = digest
        if ext in CONVERT:
            converted = assets / digest / (path.stem + CONVERT[ext])
            if not converted.exists():
                if not office_binary:
                    skipped.append({"number": number, "path": original_path, "reason": "converter_required"})
                    return
                converted.parent.mkdir(exist_ok=True)
                try:
                    result = subprocess.run(
                        [office_binary, "-env:UserInstallation=" + profile, "--headless", "--convert-to",
                         CONVERT[ext].lstrip("."), "--outdir", str(converted.parent.resolve()), str(path.resolve())],
                        capture_output=True, timeout=90,
                    )
                except subprocess.TimeoutExpired:
                    skipped.append({"number": number, "path": original_path, "reason": "conversion_timeout"})
                    return
                if result.returncode or not converted.exists():
                    skipped.append({"number": number, "path": original_path, "reason": "conversion_failed"})
                    return
            path = converted
            ext = CONVERT[ext]
            original_name = str(Path(original_name).with_suffix(ext))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        date, basis = display_date(submission + " " + original_name, item["mtime_ns"])
        label = "КП" if role == "offer" else "Документация OCR"
        date_label = date if basis == "submission_name" else "файл " + date
        prefix = f"{label} {number} · {date_label} · "
        if submission:
            prefix += submission + " · "
        filename = prefix + original_name
        if len(filename) > 500:
            filename = prefix[:180] + "…" + original_name[-(499 - len(prefix[:180])):]
        key = hashlib.sha256(original_path.encode("utf-8")).hexdigest()
        uid = hashlib.sha256((row["id"] + key + digest).encode("utf-8")).hexdigest()
        entries.append({
            "uid": uid, "registry_id": row["id"], "number": number,
            "path": str(path.resolve()), "filename": filename,
            "content_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "size": path.stat().st_size, "file_sha256": digest,
            "source": {"kind": role, "key": key, "sha256": digest,
                       "original_sha256": original_digest, "path": original_path,
                       "date": date, "date_basis": basis, "submission": submission},
        })

    offers = [item for item in manifest["entries"] if item["role"] == "offer"]
    recognized = [item for item in manifest["entries"]
                  if item["role"] == "ocr" and item["relative_path"].endswith("_results.md")]
    for item in sorted(offers + recognized, key=lambda item: item["ext"] == ".zip"):
        relative = Path(item["relative_path"])
        path = root / relative
        parts = relative.parts
        submission = parts[2] if item["role"] == "offer" and len(parts) > 3 else ""
        try:
            raw = path.read_bytes()
        except OSError:
            skipped.append({"number": item["number"], "path": str(path), "reason": "source_read_failed"})
            continue
        if item["ext"] == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(raw), metadata_encoding="cp866") as archive:
                    for member in archive.infolist():
                        if member.is_dir():
                            continue
                        name = PurePosixPath(member.filename.replace("\\", "/")).name
                        if name.startswith("~$") or name in {"Thumbs.db", "desktop.ini"}:
                            continue
                        try:
                            content = archive.read(member)
                        except (zipfile.BadZipFile, RuntimeError, OSError):
                            skipped.append({"number": item["number"], "path": str(path) + "::" + member.filename,
                                            "reason": "archive_member_unreadable"})
                            continue
                        add(item, content, str(path) + "::" + member.filename, name,
                            submission, archive=True)
            except zipfile.BadZipFile:
                skipped.append({"number": item["number"], "path": str(path), "reason": "archive_unreadable"})
        else:
            add(item, raw, str(path), path.name, submission)
    calculations = json.loads(calculation_manifest.read_text(encoding="utf-8"))
    for entry in calculations["entries"]:
        if entry["status"] != "collected":
            skipped.append({"number": entry["number"], "reason": entry["status"]})
            continue
        path = calculation_manifest.parent / entry["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        source_key = hashlib.sha256(("tenderhub:" + entry["tender_id"]).encode()).hexdigest()
        identity_digest = entry.get("source_sha256", digest)
        entries.append({
            "uid": hashlib.sha256((entry["registry_id"] + source_key + identity_digest).encode()).hexdigest(),
            "registry_id": entry["registry_id"], "number": entry["number"],
            "path": str(path.resolve()), "filename": path.name,
            "content_type": "text/markdown", "size": path.stat().st_size,
            "file_sha256": digest,
            "source": {"kind": "tenderhub_calculation", "key": source_key,
                       "sha256": identity_digest, "tender_id": entry["tender_id"],
                       "version": entry["version"], "archived": entry["calculation_archived"],
                       "scope_matches_registry": entry["scope_matches_registry"],
                       "fetched_at": calculations["fetched_at"]},
        })
    result = {"entries": entries, "skipped": skipped}
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--share-manifest", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--calculations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--office-binary", default=shutil.which("soffice"))
    args = parser.parse_args()
    report = stage(
        json.loads(args.share_manifest.read_text(encoding="utf-8")),
        json.loads(args.registry.read_text(encoding="utf-8-sig")),
        args.calculations, args.output, args.office_binary,
    )
    print(json.dumps({"documents": len(report["entries"]),
                      "by_kind": dict(Counter(entry["source"]["kind"] for entry in report["entries"])),
                      "skipped": dict(Counter(entry["reason"] for entry in report["skipped"]))}))


if __name__ == "__main__":
    main()
