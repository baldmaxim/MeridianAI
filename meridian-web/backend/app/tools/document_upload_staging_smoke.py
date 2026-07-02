"""Document upload staging smoke tool (Этап 23).

Безопасная ручная проверка presigned-S3 загрузки документа end-to-end на staging:
  initiate → PUT в S3 → confirm → (опц.) ждать processing status.

Сеть ТОЛЬКО при явном ручном запуске (main / run_smoke). Импорт модуля сети не делает; юнит-тесты
передают fake-session. Вывод — строго JSON.

Безопасность: НИКОГДА не печатает auth token, presigned URL, upload token, S3 key, имя файла, байты
файла. document_id/file_id — только sha256[:16]. HTTP-ошибки — через safe_provider_error_summary
(status/body_hash/chars, без тела/URL).

CLI:
  MERIDIAN_SMOKE_TOKEN=… python -m app.tools.document_upload_staging_smoke \
      --base-url https://staging.example --meeting-id 123 --kind txt --wait-processing
  python -m app.tools.document_upload_staging_smoke --dry-run-config

Exit: 0 ок; 2 config/env/token; 3 неверные аргументы; 4 staging failed / legacy не разрешён;
      5 upload ок, но processing не стал ready в таймаут.
"""

import argparse
import json
import os
import sys
import time

from ..core.context.canary_trace_filter import hash_filter_token
from ..core.transcription.provider_error_safety import safe_provider_error_summary

_SMOKE_CONTENT_TYPES = {"text/plain", "application/pdf"}
_PROCESSING_TERMINAL = {"ready", "error"}

# Минимальный синтетический PDF (структурно валиден для загрузки; текст «MERIDIAN smoke»).
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>"
    b"/MediaBox[0 0 300 144]/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 44>>stream\n"
    b"BT /F1 18 Tf 20 100 Td (MERIDIAN smoke) Tj ET\n"
    b"endstream endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


class _RespError(Exception):
    """Носитель response для safe_provider_error_summary (без raw тела в выводе)."""

    def __init__(self, resp):
        self.response = resp


def build_synthetic_file(kind: str) -> tuple[bytes, str, str, str]:
    """(bytes, content_type, ext, filename). Синтетика без реальных данных."""
    if kind == "pdf":
        return _MINIMAL_PDF, "application/pdf", ".pdf", "meridian_smoke.pdf"
    return (b"MERIDIAN staging smoke test\nsynthetic, no real data\n",
            "text/plain", ".txt", "meridian_smoke.txt")


def _safe_http_error(exc_or_resp) -> dict:
    if isinstance(exc_or_resp, Exception):
        return safe_provider_error_summary(exc_or_resp, provider="staging")
    return safe_provider_error_summary(_RespError(exc_or_resp), provider="staging")


def _is_2xx(resp) -> bool:
    return 200 <= getattr(resp, "status_code", 0) < 300


def run_smoke(cfg: dict, *, session=None) -> tuple[dict, int]:
    """Выполнить smoke. Возвращает (output_dict, exit_code). Сеть — через session."""
    t0 = time.monotonic()
    out: dict = {
        "status": "failed", "upload_mode": None,
        # network_smoke_executed=True только когда реально пошли в сеть (для pilot readiness gate,
        # чтобы отличать выполненный E2E от not-executed wrapper).
        "network_smoke_executed": False,
        "document_id_hash": None, "file_id_hash": None,
        "content_type": None, "size_bytes": None,
        "initiate_ok": False, "put_ok": False, "confirm_ok": False,
        "processing_status": None, "duration_ms": None, "safe_checks": {},
    }
    token = os.environ.get(cfg["auth_token_env"], "") or ""
    upload_url = None
    document_id = None
    filename = None
    content_type = None

    def finalize(code: int) -> tuple[dict, int]:
        out["duration_ms"] = int((time.monotonic() - t0) * 1000)
        blob = json.dumps(out, ensure_ascii=False)
        # id_hashed: если id был — в вывод попал именно хэш (не сырой id), а не substring-скан
        # (сырой мелкий id вроде «42» случайно встречается внутри hex-хэша — это не утечка).
        doc_hash = out.get("document_id_hash")
        out["safe_checks"] = {
            "no_token_in_output": (not token) or token not in blob,
            "no_url_in_output": (not upload_url) or upload_url not in blob,
            "no_filename_in_output": (not filename) or filename not in blob,
            "id_hashed": document_id is None or (bool(doc_hash) and doc_hash != str(document_id)),
            "content_type_allowed": content_type in _SMOKE_CONTENT_TYPES,
        }
        return out, code

    if not token:
        out["error"] = "auth_token_missing"
        return finalize(2)

    file_bytes, content_type, ext, filename = build_synthetic_file(cfg["kind"])
    out["content_type"] = content_type
    out["size_bytes"] = len(file_bytes)

    sess = session or _new_session()
    base = str(cfg["base_url"]).rstrip("/")
    auth = {"Authorization": f"Bearer {token}"}
    timeout = cfg["http_timeout"]
    out["network_smoke_executed"] = True  # с этого момента идём в сеть

    # 1) initiate
    try:
        r = sess.post(f"{base}/api/documents/upload-session",
                      json={"filename": filename, "content_type": content_type,
                            "size_bytes": len(file_bytes), "meeting_id": cfg.get("meeting_id")},
                      headers=auth, timeout=timeout)
    except Exception as e:  # noqa: BLE001 — сетевые/HTTP
        out["error"] = _safe_http_error(e)
        return finalize(4)
    if not _is_2xx(r):
        out["error"] = _safe_http_error(r)
        return finalize(4)
    data = r.json()
    mode = data.get("upload_mode")
    out["upload_mode"] = mode
    out["initiate_ok"] = True

    # 2a) legacy fallback
    if mode == "legacy_multipart":
        if not cfg["allow_legacy"]:
            out["status"] = "legacy_fallback"
            return finalize(4)
        try:
            rl = sess.post(f"{base}/api/documents/upload",
                           files={"file": (filename, file_bytes, content_type)},
                           data={"doc_type": "other"}, headers=auth, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            out["error"] = _safe_http_error(e)
            return finalize(4)
        if not _is_2xx(rl):
            out["error"] = _safe_http_error(rl)
            return finalize(4)
        out["put_ok"] = True
        out["confirm_ok"] = True
        out["status"] = "ok"
        return finalize(0)

    # 2b) s3 presigned
    document_id = data.get("document_id")
    file_id = data.get("file_id")
    upload_url = data.get("upload_url")
    put_headers = data.get("headers") or {}
    out["document_id_hash"] = hash_filter_token(str(document_id)) if document_id is not None else None
    out["file_id_hash"] = hash_filter_token(str(file_id)) if file_id is not None else None
    if not upload_url or document_id is None:
        out["error"] = "initiate_missing_url_or_id"
        return finalize(4)

    # PUT в S3 (БЕЗ Authorization — только подписанные заголовки из initiate)
    try:
        rp = sess.put(upload_url, data=file_bytes, headers=put_headers, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        out["error"] = _safe_http_error(e)
        return finalize(4)
    if not _is_2xx(rp):
        out["error"] = _safe_http_error(rp)
        return finalize(4)
    out["put_ok"] = True

    # confirm
    try:
        rc = sess.post(f"{base}/api/documents/{document_id}/confirm-upload",
                       headers=auth, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        out["error"] = _safe_http_error(e)
        return finalize(4)
    if not _is_2xx(rc):
        out["error"] = _safe_http_error(rc)
        return finalize(4)
    out["confirm_ok"] = True
    try:
        out["processing_status"] = rc.json().get("status")
    except Exception:  # noqa: BLE001
        out["processing_status"] = None

    # опционально ждать обработки
    if cfg.get("wait_processing"):
        final_status, timed_out = _poll_processing(sess, base, auth, document_id, cfg)
        out["processing_status"] = final_status
        if timed_out:
            out["status"] = "processing_timeout"
            return finalize(5)

    out["status"] = "ok"
    return finalize(0)


def _poll_processing(sess, base, auth, document_id, cfg) -> tuple[str | None, bool]:
    """Опрос GET /api/documents/{id}.status до ready/error или таймаута. (status, timed_out)."""
    deadline = time.monotonic() + float(cfg.get("processing_timeout", 60))
    interval = float(cfg.get("poll_interval", 2))
    last = None
    while True:
        try:
            rs = sess.get(f"{base}/api/documents/{document_id}", headers=auth,
                          timeout=cfg["http_timeout"])
            if _is_2xx(rs):
                last = (rs.json() or {}).get("status")
        except Exception:  # noqa: BLE001 — опрос устойчив к разовым сбоям
            pass
        if last in _PROCESSING_TERMINAL:
            return last, False
        if time.monotonic() >= deadline:
            return last, True
        time.sleep(interval)


def _new_session():
    import requests
    return requests.Session()


def _dry_run_config(cfg: dict) -> dict:
    """Безопасный конфиг без сети: имя env-переменной, но НЕ её значение."""
    token_present = bool(os.environ.get(cfg["auth_token_env"], ""))
    return {
        "status": "dry_run",
        "base_url_present": bool(cfg.get("base_url")),
        "kind": cfg["kind"],
        "meeting_id_present": cfg.get("meeting_id") is not None,
        "auth_token_env": cfg["auth_token_env"],
        "auth_token_present": token_present,
        "wait_processing": bool(cfg.get("wait_processing")),
        "allow_legacy": bool(cfg.get("allow_legacy")),
        "http_timeout": cfg["http_timeout"],
    }


def _main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.document_upload_staging_smoke",
        description="Безопасный staging smoke presigned-S3 загрузки документа (Этап 23).")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--auth-token-env", default="MERIDIAN_SMOKE_TOKEN")
    parser.add_argument("--meeting-id", type=int, default=None)
    parser.add_argument("--kind", choices=["txt", "pdf"], default="txt")
    parser.add_argument("--wait-processing", action="store_true")
    parser.add_argument("--processing-timeout", type=float, default=60.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--http-timeout", type=float, default=15.0)
    parser.add_argument("--allow-legacy", action="store_true")
    parser.add_argument("--dry-run-config", action="store_true")
    parser.add_argument("--output", default=None)
    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3

    cfg = {
        "base_url": ns.base_url, "auth_token_env": ns.auth_token_env, "meeting_id": ns.meeting_id,
        "kind": ns.kind, "wait_processing": ns.wait_processing,
        "processing_timeout": ns.processing_timeout, "poll_interval": ns.poll_interval,
        "http_timeout": ns.http_timeout, "allow_legacy": ns.allow_legacy,
    }

    if ns.dry_run_config:
        result, code = _dry_run_config(cfg), 0
    else:
        if not ns.base_url:
            print(json.dumps({"status": "failed", "error": "base_url_required"}, ensure_ascii=False))
            return 2
        result, code = run_smoke(cfg)

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
