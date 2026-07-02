"""Safe provider error logging (Этап 20)."""

import json

from app.core.transcription.provider_error_safety import (
    redact_provider_error_text,
    safe_provider_error_summary,
)


class _Resp:
    def __init__(self, status_code=429, text='{"detail":"rate limited"}', content_type="application/json"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}


class _HTTPErr(Exception):
    def __init__(self, resp):
        self.response = resp


def test_summary_no_raw_body():
    summ = safe_provider_error_summary(_HTTPErr(_Resp(text='{"detail":"secret transcript body"}')),
                                       provider="elevenlabs_batch")
    blob = json.dumps(summ, ensure_ascii=False)
    assert "secret transcript body" not in blob
    assert "response_body_preview" not in summ  # preview off by default


def test_summary_has_status_hash_chars():
    summ = safe_provider_error_summary(_HTTPErr(_Resp(status_code=500, text="ABCDEF")), provider="p")
    assert summ["status_code"] == 500
    assert summ["response_body_chars"] == 6
    assert isinstance(summ["response_body_hash"], str) and len(summ["response_body_hash"]) == 16
    assert summ["content_type"] == "application/json"
    assert summ["provider"] == "p"


def test_summary_no_response():
    summ = safe_provider_error_summary(RuntimeError("boom"), provider="elevenlabs_batch")
    assert summ["error_type"] == "RuntimeError"
    assert summ["status_code"] is None
    assert summ["response_body_hash"] is None


def test_summary_redacts_secrets_in_body_hash_only():
    body = 'Authorization: Bearer sk_live_ABCDEFGH12345678 xi-api-key: secret123'
    summ = safe_provider_error_summary(_HTTPErr(_Resp(text=body)), provider="p")
    blob = json.dumps(summ, ensure_ascii=False)
    assert "sk_live_ABCDEFGH12345678" not in blob
    assert "secret123" not in blob
    assert "Bearer" not in blob or "Bearer [REDACTED]" in blob  # no raw bearer token


def test_redact_disabled_by_default():
    assert redact_provider_error_text("Authorization: Bearer sk_live_ABCDEFGH12345678", 0) is None
    assert redact_provider_error_text("anything", -1) is None


def test_redact_enabled_truncates_and_redacts():
    body = '{"detail":"rate limited","auth":"Authorization: Bearer sk_live_ABCDEFGH12345678","k":"xi-api-key: secret123"}'
    red = redact_provider_error_text(body, max_chars=500)
    assert red is not None
    assert "sk_live_ABCDEFGH12345678" not in red
    assert "secret123" not in red
    assert "rate limited" in red  # non-secret content preserved
    # truncation (текст из коротких слов — не редактируется, только обрезается)
    assert len(redact_provider_error_text("word " * 200, max_chars=50)) == 50


def test_redact_x_api_key_and_long_token():
    red = redact_provider_error_text("x-api-key=KEY9988776655AABBCC", max_chars=200)
    assert "KEY9988776655AABBCC" not in red
    red2 = redact_provider_error_text("token " + "A" * 60, max_chars=200)
    assert "A" * 60 not in red2


def test_redact_json_quoted_header_value():
    # Этап 20 review: JSON-кавычки вокруг значения ключа должны редактироваться
    red = redact_provider_error_text('{"x-api-key": "myrandomkey123456"}', max_chars=200)
    assert "myrandomkey123456" not in red
    red2 = redact_provider_error_text('{"authorization": "Bearer secrettoken99"}', max_chars=200)
    assert "secrettoken99" not in red2


def test_redact_long_token_after_paren():
    # Этап 20 review: 40+ токен без word-boundary слева (после '(') тоже редактируется
    tok = "a1b2c3d4e5" * 5  # 50 chars
    red = redact_provider_error_text(f"error: ({tok})", max_chars=200)
    assert tok not in red


def test_content_type_redacted():
    # Этап 20 review: враждебный content-type с ключом редактируется
    resp = _Resp(content_type="application/json; x-api-key=sk_live_LEAKED12345678")
    summ = safe_provider_error_summary(_HTTPErr(resp), provider="p")
    assert "sk_live_LEAKED12345678" not in json.dumps(summ, ensure_ascii=False)


def test_summary_preview_when_enabled(monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "transcription_provider_error_body_preview_enabled", True)
    monkeypatch.setattr(s, "transcription_provider_error_body_preview_max_chars", 100)
    summ = safe_provider_error_summary(
        _HTTPErr(_Resp(text='{"detail":"rate limited","k":"Bearer sk_live_SECRETKEY12345"}')), provider="p")
    assert "response_body_preview" in summ
    assert "sk_live_SECRETKEY12345" not in summ["response_body_preview"]
    assert "rate limited" in summ["response_body_preview"]
