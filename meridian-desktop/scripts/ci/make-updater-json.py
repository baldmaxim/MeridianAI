#!/usr/bin/env python3
"""Собирает latest.json для tauri-plugin-updater из артефактов сборки.

Использование:
  make-updater-json.py <папка-с-артефактами> <tag> <owner/repo> <tauri.conf.json>

В папке ожидаются:
  *-setup.exe + *-setup.exe.sig   -> windows-x86_64 (NSIS)
  *.app.tar.gz + *.app.tar.gz.sig -> darwin-aarch64
Результат — <папка>/latest.json. Содержимое .sig подписывает приватный ключ из CI.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def find_one(folder: Path, pattern: str) -> Path | None:
    found = sorted(folder.rglob(pattern))
    if len(found) > 1:
        sys.exit(f"Найдено несколько файлов по маске {pattern}: {[f.name for f in found]}")
    return found[0] if found else None


def main() -> None:
    folder, tag, repo, conf_path = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
    version = json.loads(conf_path.read_text(encoding="utf-8"))["version"]
    if tag != f"desktop-v{version}":
        sys.exit(f"Тег {tag} не совпадает с версией {version} в tauri.conf.json (ожидается desktop-v{version})")

    targets = {
        "windows-x86_64": "*-setup.exe",
        "darwin-aarch64": "*.app.tar.gz",
    }
    platforms = {}
    for key, pattern in targets.items():
        artifact = find_one(folder, pattern)
        if artifact is None:
            sys.exit(f"Нет артефакта {pattern} для {key}")
        sig = artifact.with_name(artifact.name + ".sig")
        if not sig.is_file():
            sys.exit(f"Нет подписи {sig.name}")
        platforms[key] = {
            "signature": sig.read_text(encoding="utf-8").strip(),
            "url": f"https://github.com/{repo}/releases/download/{tag}/{quote(artifact.name)}",
        }

    latest = {
        "version": version,
        "notes": f"Meridian Desktop {version}",
        "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": platforms,
    }
    (folder / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"latest.json: версия {version}, платформы {', '.join(platforms)}")


if __name__ == "__main__":
    main()
