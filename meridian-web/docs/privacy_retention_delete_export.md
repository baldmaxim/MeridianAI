# Privacy / Retention / Delete / Export Controls (Этап 25)

Production-ready privacy controls для ОДНОЙ встречи: inventory, export-manifest, delete-plan,
guarded hard-delete, retention cleanup CLI. Safe-by-default, без миграций. Инвентарь данных —
[data_retention_inventory.md](data_retention_inventory.md). Staging E2E + evidence + pilot gate
(smoke/log-analysis/evidence report, Этап 26) — [privacy_staging_e2e.md](privacy_staging_e2e.md).

## Config (safe defaults)

| Флаг | Default | Смысл |
|---|---|---|
| `PRIVACY_CONTROLS_ENABLED` | `true` | inventory/export/delete-plan доступны |
| `PRIVACY_EXPORT_ENABLED` | `true` | экспорт разрешён |
| `PRIVACY_HARD_DELETE_ENABLED` | `false` | **жёсткое удаление выключено** (execute → 403) |
| `PRIVACY_DELETE_REQUIRE_DRY_RUN_FIRST` | `true` | execute требует confirmation_token из delete-plan |
| `PRIVACY_DELETE_MAX_MEETINGS_PER_RUN` | `50` | лимит retention cleanup за прогон |
| `PRIVACY_CONFIRMATION_TTL_MINUTES` | `30` | TTL confirmation_token |
| `RETENTION_CLEANUP_ENABLED` | `false` | retention CLI execute выключен |
| `RETENTION_DEFAULT_DAYS` / `_AUDIO_` / `_TRACE_` / `_DOCUMENT_` / `_MEETING_DATA_DAYS` | 180/30/30/180/180 | окна хранения |

## Inventory

`GET /api/meetings/{id}/privacy/inventory` → `PrivacyInventoryReport`: items по категориям
(meeting/transcript/audio/suggestion/summary/speaker_identity/document/document_chunk/job/learning/
trace/storage_object) с `count`, `storage_backend`, `safe_ref`, `deletable`, `exportable`,
`shared_reference`, `warning`. Read-only, без raw content. Shared-документы помечены
`shared_reference=true`.

## Export

`GET /api/meetings/{id}/privacy/export?include_documents=&include_audio=&format=json` →
`PrivacyExportManifest` (JSON v1). Секции: meeting-метаданные, transcript (текст — это контент
пользователя), suggestions, summary/protocol, speaker_roles, documents (**только метаданные**, без
raw filename/S3 key), audio (метаданные). RAW документы/аудио байтами в v1 **не бандлятся**
(`includes_raw_documents/_audio=false`); при запросе — warning. Логи export — только секции+counts.

## Delete-plan (dry-run)

`POST /api/meetings/{id}/privacy/delete-plan` body `{include_documents,include_audio,include_meeting_record}`
→ `PrivacyDeletePlan` (`dry_run=true`): items с `action`
(delete_db_rows|delete_local_file|delete_s3_object|cancel_job|skip_shared|skip_unsupported),
`count`, `safe_ref`, `will_delete`, `reason`. Если `PRIVACY_HARD_DELETE_ENABLED=true` — возвращает
`confirmation_token` (HMAC/JWT, TTL). Права: **создатель встречи или админ**.

## Hard delete (execute)

`DELETE /api/meetings/{id}/privacy/data` body `{confirmation_token,include_documents,include_audio,include_meeting_record}`.
Гейты (все обязательны):
1. `PRIVACY_HARD_DELETE_ENABLED=true` (иначе безопасный 403);
2. права создатель/админ;
3. при `PRIVACY_DELETE_REQUIRE_DRY_RUN_FIRST=true` — валидный `confirmation_token` (совпадение
   meeting_id/user/флагов, не протух).

Порядок удаления: cancel pending jobs → documents+chunks+S3 (shared-aware) → meeting_documents links →
audio (S3+batch+local guarded) → content-таблицы (transcript/suggestions/summary/speaker) →
meeting: text-wipe (по умолчанию) ИЛИ полное удаление записи (`include_meeting_record=true`).
Ошибки собираются → `partial_delete=true` (не притворяемся успехом). Всё в dry_run — без сети/удаления.

## Retention cleanup CLI

```
python -m app.tools.retention_cleanup --dry-run
python -m app.tools.retention_cleanup --dry-run --older-than-days 180
python -m app.tools.retention_cleanup --execute --older-than-days 180
```
Default dry-run. `--execute` требует `RETENTION_CLEANUP_ENABLED=true` И `PRIVACY_HARD_DELETE_ENABLED=true`
(иначе `status=blocked`, exit 4). Не больше `PRIVACY_DELETE_MAX_MEETINGS_PER_RUN`. Вывод — JSON:
`meeting_count`, `skipped_count`, `deleted_counts`, `warnings`. Без raw titles/filenames/text.

## Что v1 УДАЛЯЕТ и что ПРОПУСКАЕТ

- Удаляет: meeting-scoped транскрипт/подсказки/протокол/роли/контекст/эпохи, meeting_audio (S3+local),
  batch_jobs, learning-кандидаты встречи, meeting-scoped документы (не shared) + их чанки + S3.
- Пропускает (`skip_shared`): документы, привязанные к другим встречам. Одобренные user-знания
  (glossary/playbooks) и AI-профили — не трогает. Traces (app.log) — logrotate, не приложением.

## Storage deletion

S3 — только через `document_storage.delete_object` (idempotent, сеть только при явном execute).
Локальные файлы — только под `UPLOAD_DIR`/`TRANSCRIPTION_DIR` (path-traversal guard: realpath+commonpath),
иначе `skip_unsupported`.

## Rollback / recovery warning

Hard delete **необратим** (нет soft-delete/undo для контента; FileRecord помечается deleted, S3-объект
удаляется физически). Перед `--execute`/`DELETE` — бэкап БД и, при необходимости, S3 versioning.

## Privacy logging

Все события логируются через `log_privacy_event` — **только counts** (event/meeting_id/user_id/counts/
warnings). Никогда: raw transcript/audio/document text, filename, S3 key, presigned URL, API keys,
списки speaker labels.

## Operator checklist (перед pilot)

1. Убедиться `PRIVACY_HARD_DELETE_ENABLED=false` в проде, пока не готов процесс подтверждения.
2. Прогнать `retention_cleanup --dry-run` на staging → сверить counts.
3. Тест delete-plan (dry-run) на тестовой встрече → получить confirmation_token.
4. Бэкап БД + S3 versioning включён.
5. Только затем — точечный `PRIVACY_HARD_DELETE_ENABLED=true` + execute под наблюдением.
