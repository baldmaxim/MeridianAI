"""Этап 27: pilot config safety audit — safe defaults, опасные флаги, без секретов."""

import json
from types import SimpleNamespace

from app.core.pilot.pilot_config_audit import build_pilot_config_audit


def _settings(**over):
    base = dict(
        ai_signal_engine_enabled=True, ai_signal_engine_shadow_mode=True,
        ai_signal_engine_trace_include_text=False,
        ai_source_reconcile_enabled=True, ai_source_reconcile_shadow_mode=True,
        ai_audio_per_channel_stt_enabled=False, ai_audio_per_channel_stt_shadow_mode=True,
        ai_audio_per_channel_stt_provider="noop",
        privacy_hard_delete_enabled=False, retention_cleanup_enabled=False,
        transcription_provider_error_body_preview_enabled=False,
        document_s3_upload_enabled=True, s3_bucket="b", s3_region="r", s3_endpoint="e",
    )
    base.update(over)
    s = SimpleNamespace(**base)
    s.s3_enabled = bool(base["s3_bucket"] and base["s3_endpoint"])
    return s


def test_safe_defaults_ok():
    a = build_pilot_config_audit(_settings())
    assert a["safe_defaults_ok"] is True and a["dangerous_flags"] == []


def test_hard_delete_dangerous():
    a = build_pilot_config_audit(_settings(privacy_hard_delete_enabled=True))
    assert a["safe_defaults_ok"] is False and "privacy_hard_delete_enabled" in a["dangerous_flags"]


def test_retention_cleanup_dangerous():
    a = build_pilot_config_audit(_settings(retention_cleanup_enabled=True))
    assert "retention_cleanup_enabled" in a["dangerous_flags"]


def test_signal_engine_active_dangerous():
    a = build_pilot_config_audit(_settings(ai_signal_engine_shadow_mode=False))
    assert "signal_engine_active_globally" in a["dangerous_flags"]


def test_signal_engine_trace_text_dangerous():
    a = build_pilot_config_audit(_settings(ai_signal_engine_trace_include_text=True))
    assert "signal_engine_trace_include_text_enabled" in a["dangerous_flags"]


def test_source_reconcile_active_dangerous():
    a = build_pilot_config_audit(_settings(ai_source_reconcile_shadow_mode=False))
    assert "source_reconcile_active_globally" in a["dangerous_flags"]


def test_per_channel_active_dangerous():
    a = build_pilot_config_audit(_settings(ai_audio_per_channel_stt_enabled=True,
                                           ai_audio_per_channel_stt_shadow_mode=False))
    assert "per_channel_stt_active_globally" in a["dangerous_flags"]


def test_per_channel_provider_non_noop_warning():
    a = build_pilot_config_audit(_settings(ai_audio_per_channel_stt_enabled=True,
                                           ai_audio_per_channel_stt_provider="elevenlabs_batch"))
    # provider != noop при enabled = warning (не dangerous, если shadow=True)
    assert "per_channel_stt_provider_non_noop_while_enabled" in a["warnings"]
    assert a["safe_defaults_ok"] is True


def test_provider_error_preview_dangerous():
    a = build_pilot_config_audit(_settings(transcription_provider_error_body_preview_enabled=True))
    assert "provider_error_body_preview_enabled" in a["dangerous_flags"]


def test_document_s3_incomplete_warning():
    a = build_pilot_config_audit(_settings(document_s3_upload_enabled=True, s3_bucket="", s3_endpoint=""))
    assert "document_s3_upload_enabled_but_s3_incomplete" in a["warnings"]


def test_no_secrets_in_output():
    a = build_pilot_config_audit(_settings(s3_bucket="super-secret-bucket-name", s3_endpoint="https://secret.endpoint"))
    blob = json.dumps(a, ensure_ascii=False)
    assert "super-secret-bucket-name" not in blob
    assert "secret.endpoint" not in blob
    assert a["summary"]["s3_bucket_configured"] is True  # только boolean
