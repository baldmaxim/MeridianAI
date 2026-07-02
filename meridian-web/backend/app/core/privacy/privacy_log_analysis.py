"""Privacy audit/log analyzer (Этап 26).

Парсит БЕЗОПАСНЫЕ строки `log_privacy_event` (`[Privacy] event=… meeting_id=… user_id=… counts=… warnings=N`)
и выдаёт агрегат. По построению НЕ хранит сырую строку: извлекает только event_type + число warnings.
Никакой transcript/document text / filename / S3 key / token / URL в вывод не попадает, даже если
оказались в исходной строке.

CLI: python -m app.core.privacy.privacy_log_analysis /path/app.log [--output out.json]
Exit: 0 ок; 2 файл не найден/ошибка I/O; 3 неверные аргументы.
"""

import argparse
import json
import re
import sys
from collections import Counter

_KNOWN_EVENTS = {
    "privacy_inventory_viewed", "privacy_export_created", "privacy_delete_plan_created",
    "privacy_delete_executed", "retention_cleanup_dry_run", "retention_cleanup_executed",
    "privacy_unknown_event",
}

_RE_EVENT = re.compile(r"\[Privacy\]\s+event=(?P<ev>[A-Za-z_]+)\b")
_RE_WARN = re.compile(r"\bwarnings=(?P<w>\d+)\b")


def extract_privacy_event_from_line(line: str) -> dict | None:
    """Безопасное событие из строки лога или None. Сырую строку не возвращает."""
    if not line or "[Privacy]" not in line:
        return None
    m = _RE_EVENT.search(line)
    if not m:
        return None
    ev = m.group("ev")
    if ev not in _KNOWN_EVENTS:
        ev = "privacy_unknown_event"
    warn = _RE_WARN.search(line)
    return {"event": ev, "warnings": int(warn.group("w")) if warn else 0}


def load_privacy_events_from_lines(lines) -> list[dict]:
    out: list[dict] = []
    for line in lines or []:
        ev = extract_privacy_event_from_line(str(line))
        if ev is not None:
            out.append(ev)
    return out


def analyze_privacy_events(events: list[dict]) -> dict:
    events = events or []
    by_event = dict(Counter(e.get("event", "privacy_unknown_event") for e in events))

    def _c(name):
        return by_event.get(name, 0)

    # by_warning — распределение по числу warnings в событии (counts-only, без текста warning)
    by_warning = dict(Counter(str(e.get("warnings", 0)) for e in events))

    notes: list[str] = []
    if not events:
        notes.append("no_privacy_events_found")
    if _c("privacy_delete_executed"):
        notes.append("hard_delete_executed_events_present")
    if _c("retention_cleanup_executed"):
        notes.append("retention_execute_events_present")
    if any(int(k) > 0 for k in by_warning) and (_c("privacy_delete_executed") or _c("retention_cleanup_executed")):
        notes.append("execute_events_with_warnings_present")

    return {
        "total": len(events),
        "by_event_type": by_event,
        "delete_plan_count": _c("privacy_delete_plan_created"),
        "delete_executed_count": _c("privacy_delete_executed"),
        "retention_dry_run_count": _c("retention_cleanup_dry_run"),
        "retention_executed_count": _c("retention_cleanup_executed"),
        "by_warning": by_warning,
        "notes": notes,
    }


def analyze_privacy_lines(lines) -> dict:
    return analyze_privacy_events(load_privacy_events_from_lines(lines))


def _main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser(
        prog="python -m app.core.privacy.privacy_log_analysis",
        description="Безопасный анализатор privacy-audit логов (Этап 26).")
    parser.add_argument("logfile")
    parser.add_argument("--output", default=None)
    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3
    try:
        with open(ns.logfile, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Файл не найден: {ns.logfile}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return 2
    summary = analyze_privacy_lines(lines)
    blob = json.dumps(summary, ensure_ascii=False, indent=2)
    if ns.output:
        try:
            with open(ns.output, "w", encoding="utf-8") as f:
                f.write(blob)
        except OSError as e:
            print(f"Ошибка записи: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"written": ns.output, "total": summary["total"]}, ensure_ascii=False))
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
