# Presigned S3 Document Upload — hardening (Этап 22)

Загрузка документов (договоры/ВОР/сметы) идёт через presigned S3: браузер грузит файл **напрямую в
S3**, backend байты не проксирует. Этот путь уже существовал (upload-session → confirm-upload);
Этап 22 его **закалил** для production и добавил детерминированный fallback на legacy multipart.

> Важно: presigned-S3 путь уже был реализован (backend + frontend). Этап 22 НЕ вводит второй
> параллельный механизм и НЕ добавляет БД-миграций — переиспользует существующие
> `DocumentRecord.s3_key/status/file_id` + `services/s3` + job `document_process`.

## Что добавил Этап 22

- **Storage abstraction** [`services/document_storage.py`](../backend/app/services/document_storage.py) —
  тонкий слой над `services/s3`: валидация (расширение/размер/content-type), object key без raw
  filename, presigned PUT (+опц. SSE), HEAD-валидация, download-в-tempfile, `safe_storage_ref`.
- **Mode-aware initiate**: `upload-session` при выключенном S3 отдаёт `upload_mode=legacy_multipart`
  (без 503) — фронт уходит на legacy `/api/documents/upload`. dev/local/misconfigured не ломаются.
- **Content-type allow-list** на initiate + **HEAD-валидация** (существование/размер/content-type) на confirm.
- **Опциональный SSE** (`DOCUMENT_S3_SSE` / KMS) — по умолчанию выключен (без влияния на CORS).
- **Безопасные логи** `[DocumentS3Upload] initiated/completed` — без filename/URL/object key.
- **kill-switch** `DOCUMENT_S3_UPLOAD_ENABLED` поверх `s3_enabled`.

## Config

| Переменная | Default | Назначение |
|---|---|---|
| `DOCUMENT_STORAGE_BACKEND` | `local` | информативно; фактический backend = `s3`, если presigned активен |
| `DOCUMENT_S3_UPLOAD_ENABLED` | `true` | kill-switch поверх `s3_enabled`; `false` → фронт на legacy |
| `DOCUMENT_S3_PREFIX` | `documents` | префикс object key (иначе `S3_DOCUMENT_PREFIX`) |
| `DOCUMENT_S3_PRESIGN_EXPIRES_SECONDS` | `900` | TTL presigned PUT |
| `DOCUMENT_S3_MAX_UPLOAD_BYTES` | `52428800` | лимит размера (авторитетный для S3-пути) |
| `DOCUMENT_S3_ALLOWED_CONTENT_TYPES` | pdf/txt/md/csv/docx/xlsx/doc/xls | allow-list content-type |
| `DOCUMENT_S3_SSE` | `""` | server-side encryption (`AES256`/`aws:kms`); пусто = выключено |
| `DOCUMENT_S3_KMS_KEY_ID` | `""` | KMS key при `DOCUMENT_S3_SSE=aws:kms` |
| `DOCUMENT_S3_COMPLETE_HEAD_CHECK_ENABLED` | `true` | HEAD-валидация на confirm |
| `DOCUMENT_S3_BUCKET/REGION/ENDPOINT_URL/FORCE_PATH_STYLE` | `""`/`false` | forward-compat: пусто = наследовать `S3_*`. Отдельный bucket/endpoint для документов **не** подключён в этом этапе (потребует раздельного boto3-клиента, чтобы не трогать batch). |

- AWS creds — только из env/стандартной AWS-chain (`S3_ACCESS_KEY`/`S3_SECRET_KEY`), **никогда** из БД/настроек встречи.
- `DOCUMENT_S3_UPLOAD_ENABLED` по умолчанию `true` (а не `false`, как в исходной постановке): прод уже
  использует presigned-документы при заданном `S3_*`; default `false` отключил бы живой прод-путь.

## Flow

1. **initiate** — `POST /api/documents/upload-session` `{filename, content_type, size_bytes, customer_id?, object_id?}`.
   - S3 активен → создаёт `DocumentRecord(status=pending)` + `FileRecord`, отдаёт `upload_mode=s3_presigned`,
     `document_id`, presigned `upload_url`, `headers`, `max_upload_bytes`.
   - S3 выключен → `upload_mode=legacy_multipart`, `legacy_upload_url`.
2. **browser PUT** — прямой `PUT upload_url` c `headers` (Content-Type + опц. `x-amz-server-side-encryption*`). Backend байты не видит.
3. **complete** — `POST /api/documents/{document_id}/confirm-upload`: HEAD (существование/размер/content-type),
   `status=uploaded`, enqueue job `document_process`.
4. **processing/RAG** — job скачивает объект в secure tempfile (`download_to_tempfile`), извлекает текст
   (PDF-страницы/XLSX-листы/txt), режет на `DocumentChunk`, удаляет tempfile. Ретрив — по чанкам ready+included документов встречи.

## Legacy fallback (dev/local)

`DOCUMENT_S3_UPLOAD_ENABLED=false` или S3 не сконфигурирован → initiate отдаёт `legacy_multipart`; очередь
загрузки (`useDocumentUploadQueue`) грузит файл multipart-ом в `POST /api/documents/upload` (in-memory
session-документ). Старый путь остаётся рабочим — dev не требует S3.

## Privacy

- **Object key без raw filename**: `documents/{uuid32}{ext}` (`s3.object_key` → uuid+extension). Имя файла в ключ не попадает.
- **Логи**: `[DocumentS3Upload] initiated/completed user_id=… content_type=… size=… ext=… ref=…`, где
  `ref` = `safe_storage_ref` (sha256[:10]+ext). Никаких filename / presigned URL / bucket-key / token / текста документа.
- **Публичный ответ** `DocumentResponse` не содержит `s3_key`/`s3_bucket`/`extracted_text_s3_key`/URL.
- **Обработка** логирует только `document_id` + счётчики, не текст (`document_processing.py`).

## S3 CORS

Bucket CORS должен разрешать прямой PUT из браузера:
- `AllowedMethods: PUT` (и `GET`, если нужен presigned-download);
- `AllowedOrigins: <домен фронтенда>`;
- `AllowedHeaders: Content-Type` (+ `x-amz-server-side-encryption`, `x-amz-server-side-encryption-aws-kms-key-id`, если включён SSE);
- `ExposeHeaders: ETag`.

> Content-Type в presigned PUT **не подписывается** (проще CORS, нет рассинхрона подписи) — content-type
> контролируется валидацией на initiate + HEAD на confirm. SSE-заголовки подписываются, только если `DOCUMENT_S3_SSE` задан.

## Rollout

1. Включить в staging: задать `S3_*` (+ опц. `DOCUMENT_S3_*`), настроить bucket CORS.
2. Проверить: initiate → браузер PUT (200) → confirm → job `document_process` → `status=ready` + чанки.
3. Проверить приватность логов (`ref=s3:…`, без filename/URL).
4. Прод: тот же bucket/креды; для отката — `DOCUMENT_S3_UPLOAD_ENABLED=false` (мгновенный fallback на legacy).

Пошаговый staging E2E + bucket CORS + smoke-CLI + анализатор логов (Этап 23):
[document_upload_staging_e2e.md](document_upload_staging_e2e.md), пример CORS — [s3_cors_policy.example.json](s3_cors_policy.example.json).

Удаление/экспорт/retention документов и данных встречи (Этап 25) — включая удаление S3-объектов
и shared-документов: [privacy_retention_delete_export.md](privacy_retention_delete_export.md),
инвентарь — [data_retention_inventory.md](data_retention_inventory.md).

## Troubleshooting

- **PUT 403** — presigned протух (TTL) / несовпадение подписи: браузер шлёт лишний подписанный заголовок
  (Content-Type подписывать не нужно), либо SSE-заголовки не совпадают. Проверить `headers` из initiate.
- **CORS-ошибка в браузере** — bucket CORS не разрешает Origin/метод/заголовки (см. выше).
- **confirm 400 «Объект не загружен»** — HEAD не нашёл объект (PUT не завершился) или размер/тип вне лимитов.
- **Документ в `error`** — job не смог извлечь текст (пустой/сканированный PDF) или у worker нет доступа к S3
  (worker использует те же `S3_*` креды; передаётся object key, не presigned URL).

## Токен pending-загрузки — почему без него

Исходная постановка предлагала signed upload-token (чтобы избежать новой таблицы). Здесь он **не
нужен**: pending-загрузка уже персистится в `DocumentRecord(status=pending, created_by_user_id, s3_key)` —
это и есть привязка к пользователю (проверка `created_by_user_id`), срок жизни (presign TTL) и точка
HEAD-валидации на confirm. Отдельный HMAC-токен дублировал бы существующий механизм без выгоды.
