# Privacy Controls — Staging E2E + Pilot Gate (Этап 26)

Проверка privacy-контролов (Этап 25) на staging перед пилотом: inventory → export → delete-plan
(dry-run) → один точечный hard-delete execute → post-delete inventory → анализ логов → evidence
report. Ничего не удаляется автоматически. Поверх [privacy_retention_delete_export.md](privacy_retention_delete_export.md).

## Prerequisites

- `STAGING_BASE_URL` (напр. `https://staging.<домен>`);
- `MERIDIAN_SMOKE_TOKEN` — JWT пилотного пользователя (creator/admin встречи), из env, не печатать;
- тестовая `meeting_id`;
- **бэкап БД** + S3 versioning/бэкап (hard delete необратим);
- `PRIVACY_HARD_DELETE_ENABLED=false` для dry-run; `true` — только на точечный execute-тест;
- для execute: `MERIDIAN_PRIVACY_CONFIRM_TOKEN` — confirmation_token из ответа `POST delete-plan`.

## Команды

1. **Dry-run smoke** (inventory + export + delete-plan, без DELETE):
   ```
   MERIDIAN_SMOKE_TOKEN=… python -m app.tools.privacy_staging_smoke \
       --base-url <STAGING_BASE_URL> --meeting-id <ID> --dry-run \
       [--include-documents --include-audio] \
       --output staging_evidence/privacy_staging_smoke.safe.json
   ```
2. **delete-plan API** (получить confirmation_token для шага 4):
   ```
   POST /api/meetings/<ID>/privacy/delete-plan  {"include_documents":true,"include_audio":true}
   → dry-run план + confirmation_token (положить в MERIDIAN_PRIVACY_CONFIRM_TOKEN, не логировать)
   ```
3. **retention dry-run** (evidence-вход):
   ```
   python -m app.tools.retention_cleanup --dry-run --older-than-days 180 \
       --output staging_evidence/retention_dry_run.safe.json
   ```
4. **Один hard-delete execute** (только при явных флагах):
   ```
   PRIVACY_HARD_DELETE_ENABLED=true  # включить точечно на бэкенде
   MERIDIAN_SMOKE_TOKEN=… MERIDIAN_PRIVACY_CONFIRM_TOKEN=… python -m app.tools.privacy_staging_smoke \
       --base-url <STAGING_BASE_URL> --meeting-id <ID> --execute --i-understand-hard-delete \
       --confirmation-token-env MERIDIAN_PRIVACY_CONFIRM_TOKEN \
       --output staging_evidence/privacy_staging_execute.safe.json
   ```
   (execute сам делает post-delete inventory).
5. **Анализ privacy-логов**:
   ```
   python -m app.core.privacy.privacy_log_analysis /path/staging/app.log \
       --output staging_evidence/privacy_log_analysis.safe.json
   ```
6. **Evidence report** (вердикт):
   ```
   python -m app.core.privacy.privacy_evidence_report \
       --smoke-json staging_evidence/privacy_staging_smoke.safe.json \
       --privacy-log-json staging_evidence/privacy_log_analysis.safe.json \
       --retention-json staging_evidence/retention_dry_run.safe.json \
       --output staging_evidence/privacy_pilot_evidence.safe.json
   ```

## Safety

- В outputs нет raw content: только counts/statuses/hashes. `meeting_id` — sha256[:16].
- auth token и confirmation token берутся из env и НИКОГДА не печатаются (проверяется `safe_checks`).
- Export-manifest НЕ эхоится smoke-CLI — только `export_sections`/`export_counts`.
- Никаких автоматических удалений: execute требует `--execute` + `--i-understand-hard-delete` +
  `PRIVACY_HARD_DELETE_ENABLED=true` + валидный confirmation_token.
- HTTP-ошибки — safe-сводка (status/body_hash/chars), без тела/URL.

## Ожидаемые результаты

- dry-run: `status=ok`, `inventory_ok/export_ok/delete_plan_ok=true`, `safe_checks` все true.
- shared-документы: `shared_skipped_count > 0` если есть общие документы (не удаляются вслепую).
- execute: `execution_ok=true`, `partial_delete=false`, `remaining_counts_by_category` низкие/нулевые.
- S3/локальные объекты меточной встречи удалены (проверить в бакете/на диске).
- evidence verdict: `ready_for_dry_run_only` после dry-run; `ready_for_privacy_pilot` после успешного execute.

## Rollback

- Бэкап БД + S3 versioning — единственный путь восстановления; на уровне приложения hard delete
  **необратим** (S3-объект удаляется физически, контент-строки удаляются).

## Pilot gate

`ready_for_privacy_pilot` — только после успешного dry-run И одного execute-теста с
`partial_delete=false` и подтверждённым физическим удалением объектов. Иначе `ready_for_dry_run_only`
или `blocked`.
