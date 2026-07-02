"""Pilot config safety audit (Этап 27).

Проверяет, что глобальные feature-флаги в БЕЗОПАСНОМ состоянии для limited pilot: canary-слои
(Signal Engine / source_reconcile / per-channel STT) в shadow/disabled, hard delete и retention
выключены, provider error body-preview и trace_include_text выключены. Вывод — ТОЛЬКО booleans/списки
имён флагов; никаких секретов/сырых env-значений (для S3 — только *_configured booleans).

CLI: python -m app.core.pilot.pilot_config_audit
"""

import argparse
import json
import sys

from ...config import get_settings


def build_pilot_config_audit(settings) -> dict:
    dangerous: list[str] = []
    warnings: list[str] = []

    # Signal Engine: enabled+не-shadow = активен глобально (опасно для пилота)
    if settings.ai_signal_engine_enabled and not settings.ai_signal_engine_shadow_mode:
        dangerous.append("signal_engine_active_globally")
    if settings.ai_signal_engine_trace_include_text:
        dangerous.append("signal_engine_trace_include_text_enabled")

    # source_reconcile: enabled+не-shadow = активен глобально
    if settings.ai_source_reconcile_enabled and not settings.ai_source_reconcile_shadow_mode:
        dangerous.append("source_reconcile_active_globally")

    # per-channel STT: enabled+не-shadow = активен; provider != noop при enabled = внешние вызовы
    if settings.ai_audio_per_channel_stt_enabled and not settings.ai_audio_per_channel_stt_shadow_mode:
        dangerous.append("per_channel_stt_active_globally")
    if settings.ai_audio_per_channel_stt_enabled and settings.ai_audio_per_channel_stt_provider != "noop":
        warnings.append("per_channel_stt_provider_non_noop_while_enabled")

    # privacy / retention
    if settings.privacy_hard_delete_enabled:
        dangerous.append("privacy_hard_delete_enabled")
    if settings.retention_cleanup_enabled:
        dangerous.append("retention_cleanup_enabled")

    # provider error body preview (может утечь тело провайдера)
    if settings.transcription_provider_error_body_preview_enabled:
        dangerous.append("provider_error_body_preview_enabled")

    # document S3: включён, но S3 не полностью сконфигурирован → фронт молча уйдёт на legacy
    if settings.document_s3_upload_enabled and not settings.s3_enabled:
        warnings.append("document_s3_upload_enabled_but_s3_incomplete")

    summary = {
        "signal_engine_shadow": bool(settings.ai_signal_engine_shadow_mode),
        "signal_engine_enabled": bool(settings.ai_signal_engine_enabled),
        "signal_engine_trace_include_text": bool(settings.ai_signal_engine_trace_include_text),
        "source_reconcile_shadow": bool(settings.ai_source_reconcile_shadow_mode),
        "source_reconcile_enabled": bool(settings.ai_source_reconcile_enabled),
        "per_channel_stt_enabled": bool(settings.ai_audio_per_channel_stt_enabled),
        "per_channel_stt_shadow": bool(settings.ai_audio_per_channel_stt_shadow_mode),
        "per_channel_stt_provider_noop": settings.ai_audio_per_channel_stt_provider == "noop",
        "privacy_hard_delete_enabled": bool(settings.privacy_hard_delete_enabled),
        "retention_cleanup_enabled": bool(settings.retention_cleanup_enabled),
        "provider_error_body_preview_enabled": bool(settings.transcription_provider_error_body_preview_enabled),
        "document_s3_upload_enabled": bool(settings.document_s3_upload_enabled),
        "s3_enabled": bool(settings.s3_enabled),
        # только booleans присутствия — никаких сырых значений/секретов
        "s3_bucket_configured": bool(settings.s3_bucket),
        "s3_region_configured": bool(settings.s3_region),
        "s3_endpoint_configured": bool(settings.s3_endpoint),
    }
    return {
        "safe_defaults_ok": len(dangerous) == 0,
        "dangerous_flags": dangerous,
        "warnings": warnings,
        "summary": summary,
    }


def _main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser(
        prog="python -m app.core.pilot.pilot_config_audit",
        description="Аудит безопасности feature-флагов перед limited pilot (Этап 27).")
    parser.add_argument("--output", default=None)
    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3
    audit = build_pilot_config_audit(get_settings())
    blob = json.dumps(audit, ensure_ascii=False, indent=2)
    if ns.output:
        try:
            with open(ns.output, "w", encoding="utf-8") as f:
                f.write(blob)
        except OSError as e:
            print(f"Ошибка записи: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"written": ns.output, "safe_defaults_ok": audit["safe_defaults_ok"]},
                         ensure_ascii=False))
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
