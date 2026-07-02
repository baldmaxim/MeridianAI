# Limited Pilot Readiness Gate + Rollout Runbook (Этап 27)

Backend-only операторский слой, который отвечает: «Можно ли запускать limited pilot?», «Что
заблокировано?», «Какие флаги должны быть включены/выключены?», «Как откатиться?». Объединяет уже
собранные safe evidence-артефакты (Stage 20/23/24/25/26) в один вердикт. Не новая фича — финальный
gate. Не ходит в сеть/БД, не применяет PATCH, не включает canary; вывод — только statuses/counts/
booleans/categories.

## Требуемое evidence перед limited pilot

- **document staging E2E** (Stage 23/24): `document_upload_smoke.safe.json` (status=ok, S3 upload/confirm/processing ready) + `document_upload_log_analysis.safe.json`.
- **privacy dry-run** (Stage 26): `privacy_pilot_evidence.safe.json` (inventory/export/delete-plan verified; опц. hard-delete test).
- **full backend sweep** + **frontend build** → `test_evidence.safe.json` (`{"backend":{"passed":N,"failed":0},"frontend":{"build":"passed"}}`).
- **config audit** (`--include-config-audit`).

## Опциональное evidence
- **field canary report** (Stage 20): `field_canary_report.safe.json` — НЕ требуется для limited pilot, если per-channel STT не включён (должен оставаться shadow/disabled).

## Команды

```
# аудит безопасности флагов
python -m app.core.pilot.pilot_config_audit --output staging_evidence/pilot_config_audit.safe.json

# единый вердикт готовности
python -m app.core.pilot.pilot_readiness_report \
    --document-smoke staging_evidence/document_upload_smoke.safe.json \
    --document-log staging_evidence/document_upload_log_analysis.safe.json \
    --privacy-evidence staging_evidence/privacy_pilot_evidence.safe.json \
    --field-canary staging_evidence/field_canary_report.safe.json \
    --tests-json staging_evidence/test_evidence.safe.json \
    --include-config-audit --strict \
    --output staging_evidence/limited_pilot_readiness.safe.json
```
Флаги: `--include-config-audit` (аудит текущих settings), `--strict` (exit 4 при blocked/needs_evidence),
`--allow-internal-pilot-without-staging-e2e` (разрешить внутренний пилот без staging E2E).
Exit: 0 ready_*; 2 required file missing; 3 args; 4 blocked/needs_evidence под --strict.

## Вердикты

- **ready_for_limited_pilot** — document S3 E2E ok + processing ready + privacy dry-run ok + тесты зелёные + нет опасных флагов.
- **ready_for_internal_pilot** — тесты зелёные + безопасный конфиг, но staging E2E ещё нет (только внутренний, не клиентский пилот; требует `--allow-internal-pilot-without-staging-e2e`).
- **blocked** — провал document upload/processing, privacy blocked/unsafe, опасные флаги, или красные тесты.
- **needs_evidence** — нет staging document/privacy evidence и внутренний пилот не разрешён.

## Safe default matrix (проверяется config audit)

| Флаг | Ожидание для pilot | Опасно если |
|---|---|---|
| `AI_SIGNAL_ENGINE_SHADOW_MODE` | true | enabled + не shadow |
| `AI_SIGNAL_ENGINE_TRACE_INCLUDE_TEXT` | false | true |
| `AI_SOURCE_RECONCILE_SHADOW_MODE` | true | enabled + не shadow |
| `AI_AUDIO_PER_CHANNEL_STT_ENABLED` | false (или shadow) | enabled + не shadow |
| `AI_AUDIO_PER_CHANNEL_STT_PROVIDER` | noop | non-noop при enabled (warning) |
| `PRIVACY_HARD_DELETE_ENABLED` | false | true |
| `RETENTION_CLEANUP_ENABLED` | false | true |
| `TRANSCRIPTION_PROVIDER_ERROR_BODY_PREVIEW_ENABLED` | false | true |
| `DOCUMENT_S3_UPLOAD_ENABLED` | true (если S3 сконфигурирован) | true при неполном S3 (warning) |

## Разрешённые фичи limited pilot
realtime transcription, live suggestions, meeting finalization, document upload (S3) — после staging E2E.

## Должны оставаться shadow/disabled
- shadow: Signal Engine, source_reconcile.
- disabled: per-channel STT active, privacy hard delete, retention cleanup.

## Rollback matrix

| Слой | Откат |
|---|---|
| document_upload | `DOCUMENT_S3_UPLOAD_ENABLED=false` → legacy multipart (без деплоя) |
| source_reconcile | `source_reconcile_* → null` на встрече; глобальный `AI_SOURCE_RECONCILE_SHADOW_MODE=true` |
| per_channel_stt | `audio_per_channel_stt_* → null`; `AI_AUDIO_PER_CHANNEL_STT_ENABLED=false`/`SHADOW_MODE=true` |
| privacy_delete | `PRIVACY_HARD_DELETE_ENABLED=false`; восстановление только из бэкапа БД / S3 versioning (необратимо на уровне app) |
| signal_engine | `AI_SIGNAL_ENGINE_SHADOW_MODE=true` (или `AI_SIGNAL_ENGINE_ENABLED=false`) |

## Operator checklist

1. Прогнать полный backend sweep + frontend build → `test_evidence.safe.json`.
2. Выполнить document staging E2E (Stage 23/24) + privacy dry-run (Stage 26) → safe JSON.
3. `pilot_config_audit` → `safe_defaults_ok=true`, `dangerous_flags=[]`.
4. `pilot_readiness_report --strict --include-config-audit` → вердикт.
5. Только при `ready_for_limited_pilot` — запускать пилот по `pilot_scope_recommendation`, держа rollback matrix наготове.
6. Бэкап БД + S3 versioning перед любым hard-delete/execute.

## Что tool НЕ делает
Не ходит в сеть/БД, не применяет PATCH, не включает canary-флаги, не читает raw content. Читает только
safe JSON-артефакты и текущие settings (booleans). Нет staging evidence → честно `needs_evidence`/`blocked`.
