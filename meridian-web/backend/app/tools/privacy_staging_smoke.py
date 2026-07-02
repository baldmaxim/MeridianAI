"""Privacy staging smoke tool (Этап 26).

Безопасная ручная проверка privacy-контролов на staging для ОДНОЙ встречи:
  dry-run: GET inventory + GET export + POST delete-plan (НЕ вызывает DELETE);
  execute: DELETE /privacy/data (только при явных флагах) → повторный inventory.

Сеть ТОЛЬКО при ручном запуске; тесты передают fake-session. Вывод — строго JSON.
НИКОГДА не печатает: auth token, confirmation token, presigned URL/base URL, raw meeting title,
raw transcript/export content, raw document names/S3 refs. meeting_id — sha256[:16]. Export-manifest
НЕ эхоится (только sections/counts). HTTP-ошибка → safe_provider_error_summary.

CLI:
  MERIDIAN_SMOKE_TOKEN=… python -m app.tools.privacy_staging_smoke \
      --base-url https://staging.example --meeting-id 123 --dry-run [--include-documents --include-audio]
  MERIDIAN_SMOKE_TOKEN=… MERIDIAN_PRIVACY_CONFIRM_TOKEN=… python -m app.tools.privacy_staging_smoke \
      --base-url https://staging.example --meeting-id 123 --execute --i-understand-hard-delete \
      --confirmation-token-env MERIDIAN_PRIVACY_CONFIRM_TOKEN

Exit: 0 ок; 2 missing env/config; 3 неверные аргументы; 4 blocked/not allowed; 5 API failure/partial.
"""

import argparse
import json
import os
import sys
import time

from ..core.context.canary_trace_filter import hash_filter_token
from ..core.transcription.provider_error_safety import safe_provider_error_summary


class _RespError(Exception):
    def __init__(self, resp):
        self.response = resp


def _safe_http_error(exc_or_resp) -> dict:
    if isinstance(exc_or_resp, Exception):
        return safe_provider_error_summary(exc_or_resp, provider="staging")
    return safe_provider_error_summary(_RespError(exc_or_resp), provider="staging")


def _is_2xx(resp) -> bool:
    return 200 <= getattr(resp, "status_code", 0) < 300


def _new_session():
    import requests
    return requests.Session()


def run_privacy_smoke(cfg: dict, *, session=None) -> tuple[dict, int]:
    t0 = time.monotonic()
    execute = bool(cfg.get("execute"))
    out: dict = {
        "status": "failed", "mode": "execute" if execute else "dry_run",
        "meeting_id_hash": hash_filter_token(str(cfg.get("meeting_id"))),
        "blockers": [], "safe_checks": {},
    }
    token = os.environ.get(cfg["auth_token_env"], "") or ""
    secrets = {"auth": token, "confirm": ""}  # mutable holder — finalize видит обновления

    def finalize(code: int) -> tuple[dict, int]:
        out["duration_ms"] = int((time.monotonic() - t0) * 1000)
        blob = json.dumps(out, ensure_ascii=False)
        # id_hashed: проверяем, что в выводе именно хэш (не сырой id), а не substring-скан —
        # сырой мелкий id (напр. «1») случайно встречается внутри hex-хэша/duration.
        mid_hash = out.get("meeting_id_hash")
        out["safe_checks"] = {
            "no_auth_token_in_output": (not secrets["auth"]) or secrets["auth"] not in blob,
            "no_confirm_token_in_output": (not secrets["confirm"]) or secrets["confirm"] not in blob,
            "no_base_url_in_output": str(cfg.get("base_url") or "") not in blob,
            "id_hashed": bool(mid_hash) and mid_hash != str(cfg.get("meeting_id")),
        }
        return out, code

    if not token:
        out["blockers"].append("auth_token_missing")
        return finalize(2)

    sess = session or _new_session()
    base = str(cfg["base_url"]).rstrip("/")
    mid = cfg["meeting_id"]
    auth = {"Authorization": f"Bearer {token}"}
    timeout = cfg["http_timeout"]
    body = {"include_documents": bool(cfg.get("include_documents")),
            "include_audio": bool(cfg.get("include_audio")),
            "include_meeting_record": bool(cfg.get("include_meeting_record"))}

    def _get(path):
        return sess.get(f"{base}{path}", headers=auth, timeout=timeout)

    if execute:
        return _run_execute(out, sess, base, mid, auth, timeout, body, cfg, finalize, secrets)

    # --- dry-run ---
    out.update({"inventory_ok": False, "export_ok": False, "delete_plan_ok": False,
                "hard_delete_enabled": None, "requires_confirmation": None,
                "counts_by_category": {}, "delete_plan_items": 0, "shared_skipped_count": 0})
    try:
        r = _get(f"/api/meetings/{mid}/privacy/inventory")
    except Exception as e:  # noqa: BLE001
        out["error"] = _safe_http_error(e)
        return finalize(5)
    if not _is_2xx(r):
        out["error"] = _safe_http_error(r)
        out["blockers"].append("inventory_http_error")
        return finalize(5)
    inv = r.json() or {}
    out["inventory_ok"] = True
    out["counts_by_category"] = inv.get("totals") or {}

    try:
        re_ = _get(f"/api/meetings/{mid}/privacy/export?format=json")
    except Exception as e:  # noqa: BLE001
        out["error"] = _safe_http_error(e)
        return finalize(5)
    if not _is_2xx(re_):
        out["error"] = _safe_http_error(re_)
        out["blockers"].append("export_http_error")
        return finalize(5)  # HTTP-ошибка = API failure (exit 5), как inventory/delete-plan
    man = re_.json() or {}
    out["export_ok"] = True
    # НЕ эхоим data манифеста — только безопасные секции/counts
    out["export_sections"] = man.get("sections") or []
    out["export_counts"] = man.get("counts") or {}

    try:
        rp = sess.post(f"{base}/api/meetings/{mid}/privacy/delete-plan", json=body,
                       headers=auth, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        out["error"] = _safe_http_error(e)
        return finalize(5)
    if not _is_2xx(rp):
        out["error"] = _safe_http_error(rp)
        out["blockers"].append("delete_plan_http_error")
        return finalize(5)
    plan = rp.json() or {}
    out["delete_plan_ok"] = True
    out["hard_delete_enabled"] = plan.get("hard_delete_enabled")
    out["requires_confirmation"] = plan.get("requires_confirmation")
    items = plan.get("items") or []
    out["delete_plan_items"] = len(items)
    out["shared_skipped_count"] = sum(1 for it in items if it.get("action") == "skip_shared")
    # confirmation_token из плана НЕ включаем в вывод (оператор берёт его через API напрямую)

    out["status"] = "ok" if (out["inventory_ok"] and out["export_ok"] and out["delete_plan_ok"]) else "blocked"
    return finalize(0 if out["status"] == "ok" else 4)


def _run_execute(out, sess, base, mid, auth, timeout, body, cfg, finalize, secrets):
    out.update({"execution_ok": False, "partial_delete": None,
                "post_delete_inventory_ok": False, "remaining_counts_by_category": {}})
    if not cfg.get("i_understand_hard_delete"):
        out["blockers"].append("missing_--i-understand-hard-delete")
        return finalize(4)
    confirm_env = cfg.get("confirmation_token_env")
    confirm_token = os.environ.get(confirm_env, "") if confirm_env else ""
    if not confirm_token:
        out["blockers"].append("confirmation_token_missing")
        return finalize(2)
    secrets["confirm"] = confirm_token  # для safe_checks (не печатаем токен)

    del_body = dict(body)
    del_body["confirmation_token"] = confirm_token
    try:
        rd = sess.delete(f"{base}/api/meetings/{mid}/privacy/data", json=del_body,
                         headers=auth, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        out["error"] = _safe_http_error(e)
        return finalize(5)
    if not _is_2xx(rd):
        out["error"] = _safe_http_error(rd)
        out["blockers"].append("delete_http_error")
        return finalize(5)
    rep = rd.json() or {}
    out["execution_ok"] = bool(rep.get("executed"))
    out["partial_delete"] = bool(rep.get("partial_delete"))

    try:
        ri = sess.get(f"{base}/api/meetings/{mid}/privacy/inventory", headers=auth, timeout=timeout)
        if _is_2xx(ri):
            out["post_delete_inventory_ok"] = True
            out["remaining_counts_by_category"] = (ri.json() or {}).get("totals") or {}
    except Exception:  # noqa: BLE001
        pass

    if out["execution_ok"] and not out["partial_delete"]:
        out["status"] = "ok"
        return finalize(0)
    out["status"] = "partial_delete" if out["partial_delete"] else "failed"
    return finalize(5)


def _main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(
        prog="python -m app.tools.privacy_staging_smoke",
        description="Безопасный staging smoke privacy-контролов встречи (Этап 26).")
    p.add_argument("--base-url", default=None)
    p.add_argument("--auth-token-env", default="MERIDIAN_SMOKE_TOKEN")
    p.add_argument("--meeting-id", type=int, default=None)
    p.add_argument("--include-documents", action="store_true")
    p.add_argument("--include-audio", action="store_true")
    p.add_argument("--include-meeting-record", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--i-understand-hard-delete", action="store_true")
    p.add_argument("--confirmation-token-env", default="MERIDIAN_PRIVACY_CONFIRM_TOKEN")
    p.add_argument("--http-timeout", type=float, default=15.0)
    p.add_argument("--output", default=None)
    try:
        ns = p.parse_args(argv[1:])
    except SystemExit:
        return 3
    if not ns.base_url or ns.meeting_id is None:
        print(json.dumps({"status": "failed", "blockers": ["base_url_and_meeting_id_required"]},
                         ensure_ascii=False))
        return 2

    cfg = {
        "base_url": ns.base_url, "auth_token_env": ns.auth_token_env, "meeting_id": ns.meeting_id,
        "include_documents": ns.include_documents, "include_audio": ns.include_audio,
        "include_meeting_record": ns.include_meeting_record, "execute": ns.execute,
        "i_understand_hard_delete": ns.i_understand_hard_delete,
        "confirmation_token_env": ns.confirmation_token_env, "http_timeout": ns.http_timeout,
    }
    result, code = run_privacy_smoke(cfg)
    blob = json.dumps(result, ensure_ascii=False, indent=2)
    if ns.output:
        try:
            with open(ns.output, "w", encoding="utf-8") as f:
                f.write(blob)
        except OSError as e:
            print(f"Ошибка записи: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"written": ns.output, "status": result.get("status")}, ensure_ascii=False))
    else:
        print(blob)
    return code


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
