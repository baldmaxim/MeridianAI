"""Этап 23: staging smoke tool. Сеть полностью замокана (FakeSession) — ни одного реального вызова.
Проверяем режимы, exit-коды и что в выводе нет token/URL/имени файла/байтов; id хэшируются."""

import json

from app.tools import document_upload_staging_smoke as smoke

_TOKEN = "SECRET_SMOKE_TOKEN_XYZ"
_PRESIGNED = "https://bucket.s3.amazonaws.com/documents/uuid.pdf?X-Amz-Signature=LEAKSIG&X-Amz-Credential=AKIAEXAMPLE"


class FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, posts=None, puts=None, gets=None):
        self._posts = list(posts or [])
        self._puts = list(puts or [])
        self._gets = list(gets or [])
        self.calls = []

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self._posts.pop(0)

    def put(self, url, **kw):
        self.calls.append(("PUT", url, kw))
        return self._puts.pop(0)

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self._gets.pop(0) if self._gets else FakeResp(200, {"status": "ready"})


def _cfg(**over):
    c = {
        "base_url": "https://staging.example", "auth_token_env": "MERIDIAN_SMOKE_TOKEN",
        "meeting_id": 123, "kind": "txt", "wait_processing": False,
        "processing_timeout": 1, "poll_interval": 0, "http_timeout": 5, "allow_legacy": False,
    }
    c.update(over)
    return c


def _initiate_s3(**over):
    d = {"upload_mode": "s3_presigned", "document_id": 42, "file_id": 7,
         "upload_url": _PRESIGNED, "headers": {"Content-Type": "text/plain"}}
    d.update(over)
    return FakeResp(200, d)


def _assert_no_secrets(out):
    blob = json.dumps(out, ensure_ascii=False)
    assert _TOKEN not in blob
    assert "LEAKSIG" not in blob and "AKIAEXAMPLE" not in blob
    assert _PRESIGNED not in blob
    assert "meridian_smoke" not in blob  # имя файла не выводится
    assert "MERIDIAN staging smoke test" not in blob  # байты файла не выводятся


def test_s3_happy_path(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    sess = FakeSession(
        posts=[_initiate_s3(), FakeResp(200, {"document_id": 42, "status": "uploaded"})],
        puts=[FakeResp(200)],
    )
    out, code = smoke.run_smoke(_cfg(), session=sess)
    assert code == 0 and out["status"] == "ok"
    assert out["initiate_ok"] and out["put_ok"] and out["confirm_ok"]
    assert out["upload_mode"] == "s3_presigned"
    assert out["document_id_hash"] and out["document_id_hash"] != "42" and len(out["document_id_hash"]) == 16
    assert out["file_id_hash"] and len(out["file_id_hash"]) == 16
    assert all(out["safe_checks"].values())
    _assert_no_secrets(out)
    # PUT не несёт Authorization (только подписанные заголовки из initiate)
    put_call = next(c for c in sess.calls if c[0] == "PUT")
    assert "Authorization" not in (put_call[2].get("headers") or {})


def test_s3_happy_with_wait_processing(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    sess = FakeSession(
        posts=[_initiate_s3(), FakeResp(200, {"document_id": 42, "status": "uploaded"})],
        puts=[FakeResp(200)],
        gets=[FakeResp(200, {"status": "ready"})],
    )
    out, code = smoke.run_smoke(_cfg(wait_processing=True), session=sess)
    assert code == 0 and out["status"] == "ok" and out["processing_status"] == "ready"


def test_legacy_without_allow_exits_4(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    sess = FakeSession(posts=[FakeResp(200, {"upload_mode": "legacy_multipart",
                                             "legacy_upload_url": "/api/documents/upload"})])
    out, code = smoke.run_smoke(_cfg(), session=sess)
    assert code == 4 and out["status"] == "legacy_fallback"
    assert out["initiate_ok"] and not out["put_ok"]


def test_legacy_with_allow_ok(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    sess = FakeSession(posts=[
        FakeResp(200, {"upload_mode": "legacy_multipart", "legacy_upload_url": "/api/documents/upload"}),
        FakeResp(200, {"filename": "meridian_smoke.txt", "doc_type": "other", "page_count": 1}),
    ])
    out, code = smoke.run_smoke(_cfg(allow_legacy=True), session=sess)
    assert code == 0 and out["status"] == "ok" and out["upload_mode"] == "legacy_multipart"
    _assert_no_secrets(out)


def test_put_failure_safe(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    sess = FakeSession(
        posts=[_initiate_s3()],
        puts=[FakeResp(403, text='<Error><Code>AccessDenied</Code>SECRETBODY</Error>',
                       headers={"content-type": "application/xml"})],
    )
    out, code = smoke.run_smoke(_cfg(), session=sess)
    assert code == 4 and out["initiate_ok"] and out["put_ok"] is False
    assert out["error"]["status_code"] == 403
    assert "SECRETBODY" not in json.dumps(out, ensure_ascii=False)  # safe summary, без raw тела
    _assert_no_secrets(out)


def test_confirm_failure_safe(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    sess = FakeSession(
        posts=[_initiate_s3(), FakeResp(400, text="bad", headers={"content-type": "application/json"})],
        puts=[FakeResp(200)],
    )
    out, code = smoke.run_smoke(_cfg(), session=sess)
    assert code == 4 and out["put_ok"] and out["confirm_ok"] is False
    _assert_no_secrets(out)


def test_initiate_http_error_safe(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)

    class _Boom(FakeSession):
        def post(self, url, **kw):
            raise RuntimeError("connection refused to secret-host")

    out, code = smoke.run_smoke(_cfg(), session=_Boom())
    assert code == 4 and out["initiate_ok"] is False
    assert out["error"]["error_type"] == "RuntimeError"
    assert "secret-host" not in json.dumps(out, ensure_ascii=False)


def test_token_missing_exits_2(monkeypatch):
    monkeypatch.delenv("MERIDIAN_SMOKE_TOKEN", raising=False)
    out, code = smoke.run_smoke(_cfg(), session=FakeSession())
    assert code == 2 and out["status"] == "failed" and out.get("error") == "auth_token_missing"


def test_dry_run_config_no_secret(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    result = smoke._dry_run_config(_cfg())
    assert result["status"] == "dry_run"
    assert result["auth_token_env"] == "MERIDIAN_SMOKE_TOKEN"
    assert result["auth_token_present"] is True
    assert _TOKEN not in json.dumps(result, ensure_ascii=False)


def test_main_dry_run_prints_no_secret(monkeypatch, capsys):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    code = smoke._main(["prog", "--dry-run-config", "--base-url", "https://staging.example"])
    assert code == 0
    captured = capsys.readouterr()
    assert "dry_run" in captured.out
    assert _TOKEN not in captured.out


def test_main_requires_base_url(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    code = smoke._main(["prog"])  # нет --base-url и нет --dry-run-config
    assert code == 2
