# Document Upload — Staging E2E + Operations (Этап 23)

Проверка presigned-S3 загрузки документов (поверх [presigned_s3_document_upload.md](presigned_s3_document_upload.md))
на staging перед прод-rollout: bucket CORS, ручной прогон, безопасный smoke-CLI, анализатор логов.

## Требуемый bucket CORS

Браузер грузит файл напрямую в S3 (backend байты не проксирует) → бакет обязан разрешать прямой PUT.
Пример: [s3_cors_policy.example.json](s3_cors_policy.example.json).

- **AllowedMethods**: `PUT` (обязательно), `GET`/`HEAD` (если фронт качает/проверяет).
- **AllowedHeaders**:
  - `Content-Type`
  - `x-amz-server-side-encryption`, `x-amz-server-side-encryption-aws-kms-key-id` — **только** если включён `DOCUMENT_S3_SSE`.
- **AllowedOrigins**: домен staging-фронта и прод-фронта.
- **ExposeHeaders**: `ETag`.

> Content-Type в presigned PUT НЕ подписывается (проще CORS) — контроль на initiate + HEAD на confirm.
> OPTIONS-preflight обрабатывает сам S3 по CORS-правилам.

## E2E шаги

1. **Env** на backend/worker: `S3_ENDPOINT/S3_REGION/S3_BUCKET/S3_ACCESS_KEY/S3_SECRET_KEY`,
   `DOCUMENT_S3_UPLOAD_ENABLED=true` (kill-switch), опц. `DOCUMENT_S3_*`. Worker должен иметь те же S3-креды.
2. **Bucket CORS** — применить политику из примера (origins под свой домен).
3. **Ручная загрузка во фронте** — открыть встречу → «Файлы» → загрузить PDF/DOCX/XLSX/TXT; убедиться, что
   прогресс идёт и документ появляется в списке со статусом → `ready`.
4. **Smoke-CLI** (оператор, вне браузера):
   ```
   MERIDIAN_SMOKE_TOKEN=<jwt> python -m app.tools.document_upload_staging_smoke \
       --base-url https://staging.example --meeting-id 123 --kind txt --wait-processing
   ```
   Ожидаем `status=ok`, `initiate_ok/put_ok/confirm_ok=true`, `processing_status=ready`.
5. **Проверить processing** — документ `ready` и созданы чанки (`GET /api/documents/{id}` → `chunks_count>0`).
6. **Проверить логи** — есть `[DocumentS3Upload] initiated/completed` с `ref=s3:<hash><ext>` (НЕ сырой ключ),
   нет presigned URL / имени файла / текста документа. Свести:
   ```
   python -m app.core.documents.document_upload_log_analysis /path/app.log
   ```

## Smoke-CLI

- Сеть **только** при ручном запуске; синтетический файл в памяти (txt по умолчанию; `--kind pdf`).
- `--dry-run-config` — печатает безопасный конфиг (имя env-переменной, НЕ значение), без сети.
- Auth token берётся из env (`--auth-token-env`, default `MERIDIAN_SMOKE_TOKEN`) и НИКОГДА не печатается.
- Не печатает: token, presigned URL, S3 key, имя файла, байты; `document_id/file_id` — sha256[:16].
- Exit: `0` ок; `2` config/env/token; `3` неверные аргументы; `4` staging failed / legacy не разрешён;
  `5` upload ок, но processing не стал ready в таймаут.
- `--allow-legacy` — если S3 выключен и вернулся `legacy_multipart`, грузить через legacy multipart.

## Анализатор логов

`python -m app.core.documents.document_upload_log_analysis /path/app.log` → JSON-сводка:
`initiated_count/completed_count/legacy_fallback_count/failed_count`, `by_content_type/by_extension/
by_error_kind`, `completion_rate`, `notes`. По построению не эхоит сырые строки/URL/ключи/имена.

## Troubleshooting

- **403 на PUT** — presigned протух (TTL), либо браузер шлёт лишний подписанный заголовок, либо права
  бакета. Smoke выдаст безопасную сводку (status/body_hash), фронт — «Доступ к хранилищу отклонён (403)».
- **CORS preflight fail** — бакет CORS не разрешает Origin/метод/заголовки; фронт покажет «Проверьте CORS/доступ к бакету».
- **confirm 400 «Объект не загружен»** — PUT не завершился, или размер/тип вне лимитов (HEAD-валидация).
- **content-type mismatch** — HEAD вернул недопустимый content-type; расширение авторитетно, но content-type
  тоже валидируется на confirm.
- **worker не может скачать объект** — у worker нет S3-кредов/сети; job `document_process` → `error`
  (`by_error_kind=download_error`). Передаётся object key, не presigned URL.
- **legacy fallback** — `upload_mode=legacy_multipart` (S3 выключен/kill-switch) → фронт грузит multipart-ом.

## Rollback

- `DOCUMENT_S3_UPLOAD_ENABLED=false` → initiate возвращает `legacy_multipart`, фронт мгновенно уходит на
  legacy `/api/documents/upload`. presigned-путь отключается без деплоя кода.

## Privacy

- В S3 object key нет raw filename (`documents/{uuid}{ext}`).
- В логах нет presigned URL, token, S3 key (только `ref=s3:<hash><ext>`), имени файла, текста документа.
- Smoke-CLI и анализатор соблюдают те же правила (id хэшируются, URL/токен/ключи не печатаются).
