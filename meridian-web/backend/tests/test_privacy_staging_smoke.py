"""Этап 26: privacy staging smoke — сеть замокана (FakeSession). Dry-run/execute, гейты, безопасность
вывода (нет token/URL/manifest data/raw)."""

import json

from app.tools import privacy_staging_smoke as smoke

_TOKEN = "SECRET_AUTH_TOKEN_XYZ"
_CONFIRM = "SECRET_CONFIRM_TOKEN_QQQ"
_BASE = "https://staging.example"


class FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, gets=None, posts=None, deletes=None):
        self._gets = list(gets or [])
        self._posts = list(posts or [])
        self._deletes = list(deletes or [])

    def get(self, url, **kw):
        return self._gets.pop(0)

    def post(self, url, **kw):
        return self._posts.pop(0)

    def delete(self, url, **kw):
        return self._deletes.pop(0)


def _cfg(**over):
    c = {
        "base_url": _BASE, "auth_token_env": "MERIDIAN_SMOKE_TOKEN", "meeting_id": 123,
        "include_documents": True, "include_audio": True, "include_meeting_record": False,
        "execute": False, "i_understand_hard_delete": False,
        "confirmation_token_env": "MERIDIAN_PRIVACY_CONFIRM_TOKEN", "http_timeout": 5,
    }
    c.update(over)
    return c


_INV = FakeResp(200, {"totals": {"transcript": 3, "document": 1, "participant": 2}})
_EXPORT = FakeResp(200, {"sections": ["meeting", "transcript"], "counts": {"transcript": 3},
                        "data": {"transcript": [{"text": "СЕКРЕТНЫЙ_ТРАНСКРИПТ"}]}})
_PLAN = FakeResp(200, {"hard_delete_enabled": False, "requires_confirmation": True,
                      "confirmation_token": "PLANTOKEN_SHOULD_NOT_LEAK",
                      "items": [{"category": "transcript", "action": "delete_db_rows", "count": 3},
                                {"category": "document", "action": "skip_shared", "count": 1}]})


def test_dry_run_happy(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    sess = FakeSession(gets=[_INV, _EXPORT], posts=[_PLAN])
    out, code = smoke.run_privacy_smoke(_cfg(), session=sess)
    assert code == 0 and out["status"] == "ok"
    assert out["inventory_ok"] and out["export_ok"] and out["delete_plan_ok"]
    assert out["counts_by_category"]["participant"] == 2
    assert out["shared_skipped_count"] == 1
    assert all(out["safe_checks"].values())
    blob = json.dumps(out, ensure_ascii=False)
    assert _TOKEN not in blob and _BASE not in blob
    assert "СЕКРЕТНЫЙ_ТРАНСКРИПТ" not in blob            # manifest data не эхоится
    assert "PLANTOKEN_SHOULD_NOT_LEAK" not in blob        # confirmation token из плана не печатается
    assert "123" not in blob                              # meeting_id хэширован


def test_execute_happy(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    monkeypatch.setenv("MERIDIAN_PRIVACY_CONFIRM_TOKEN", _CONFIRM)
    del_resp = FakeResp(200, {"executed": True, "partial_delete": False})
    inv_after = FakeResp(200, {"totals": {"transcript": 0, "document": 0}})
    sess = FakeSession(gets=[inv_after], deletes=[del_resp])
    out, code = smoke.run_privacy_smoke(_cfg(execute=True, i_understand_hard_delete=True), session=sess)
    assert code == 0 and out["status"] == "ok"
    assert out["execution_ok"] and out["partial_delete"] is False and out["post_delete_inventory_ok"]
    blob = json.dumps(out, ensure_ascii=False)
    assert _CONFIRM not in blob and _TOKEN not in blob
    assert all(out["safe_checks"].values())


def test_execute_requires_i_understand(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    monkeypatch.setenv("MERIDIAN_PRIVACY_CONFIRM_TOKEN", _CONFIRM)
    out, code = smoke.run_privacy_smoke(_cfg(execute=True, i_understand_hard_delete=False),
                                        session=FakeSession())
    assert code == 4 and "missing_--i-understand-hard-delete" in out["blockers"]


def test_execute_missing_confirm_token(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    monkeypatch.delenv("MERIDIAN_PRIVACY_CONFIRM_TOKEN", raising=False)
    out, code = smoke.run_privacy_smoke(_cfg(execute=True, i_understand_hard_delete=True),
                                        session=FakeSession())
    assert code == 2 and "confirmation_token_missing" in out["blockers"]


def test_missing_auth_token(monkeypatch):
    monkeypatch.delenv("MERIDIAN_SMOKE_TOKEN", raising=False)
    out, code = smoke.run_privacy_smoke(_cfg(), session=FakeSession())
    assert code == 2 and "auth_token_missing" in out["blockers"]


def test_api_failure_safe(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    sess = FakeSession(gets=[FakeResp(500, text="ERRBODY_secret_leak",
                                      headers={"content-type": "text/plain"})])
    out, code = smoke.run_privacy_smoke(_cfg(), session=sess)
    assert code == 5 and out["inventory_ok"] is False
    assert out["error"]["status_code"] == 500
    assert "ERRBODY_secret_leak" not in json.dumps(out, ensure_ascii=False)


def test_export_failure_exit_5(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    sess = FakeSession(gets=[_INV, FakeResp(500, text="EXPORTERR_secret",
                                            headers={"content-type": "text/plain"})])
    out, code = smoke.run_privacy_smoke(_cfg(), session=sess)
    assert code == 5 and out["inventory_ok"] and out["export_ok"] is False
    assert "EXPORTERR_secret" not in json.dumps(out, ensure_ascii=False)


def test_main_requires_base_and_meeting(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SMOKE_TOKEN", _TOKEN)
    code = smoke._main(["prog", "--dry-run"])  # нет --base-url/--meeting-id
    assert code == 2
