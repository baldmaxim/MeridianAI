# Security Notes — MeridianAI (MVP)

## Что НЕ логируем
JSON-логи проходят через `RedactionFilter` + `JsonFormatter` ([logging_setup.py](../backend/app/logging_setup.py)),
которые маскируют:
- API-ключи, токены (JWT/access/refresh), пароли, `Authorization`, cookies;
- presigned-URL подписи S3 (`X-Amz-Signature`, `X-Amz-Credential`), `token=…` в query;
- секреты в `user:pass@host`.

Помимо этого НЕ пишем в логи:
- полный транскрипт встречи, полный prompt, текст чанков документов;
- полный payload job при потенциально чувствительном содержимом.

Хелперы для логов: `truncate_for_log` / `safe_log_value` / `redact_secrets` (logging_setup).
В логах оставляем: id, счётчики, длительности, статусы, короткие сообщения об ошибках.
`Job.last_error` обрезается до `JOB_ERROR_MAX_CHARS` (default 2000).

## Где хранятся файлы
- Документы и batch-аудио — в S3-совместимом хранилище. Ключ объекта генерируется на сервере
  (`meridian/{user_id}/{purpose}/{uuid}{ext}`) — **не из пользовательского ввода**, path traversal невозможен.
- Backend не проксирует байты файлов: загрузка/скачивание — через presigned URL (TTL `S3_PRESIGN_TTL`).
- Извлечённый текст документа хранится отдельным префиксом в S3.
- Имена файлов от пользователя проходят `safe_filename` (отклоняет `../`, `/`, `\\`, null).
- API-ключи провайдеров — в БД в зашифрованном виде (`ENCRYPTION_KEY`), не в .env/коде/логах.

## Как работают права
- **Просмотр встречи/документов:** `user_can_access_meeting` / `user_can_access_document`
  (создатель ∪ участник ∪ доступ к объекту напрямую/через отдел).
- **Изменение (запись, протокол, контекст, AI-настройки, attach/remove):** `can_record_meeting`
  (creator / participant / object edit|manage). View-only (`viewer`) — только чтение.
- **База знаний / кандидаты обучения:** scoped по `owner_user_id`.
- **AI-профили:** scoped по `owner_user_id`.
- **Health deep / recover-stale:** admin или `DEV_MODE`.
- No-access → 403/404 без раскрытия деталей.
- WebSocket: JWT валидируется при connect, `user_can_access_meeting` — обязательна; запись аудио —
  только активный источник с `can_send_audio`; бинарные фреймы > `WS_MAX_BINARY_FRAME_BYTES` отклоняются.

## Ограничения MVP
- RoomRegistry — in-memory (один процесс). Масштабирование/Redis pub-sub — отдельный этап (seam в `RoomRegistry`).
- Rate limiting — на ключевых auth-эндпоинтах (slowapi); сплошного нет.
- STT завязан на провайдера из настроек; полноценный мульти-STT switch — частично.
- Нет встроенного аудита доступа к каждому файлу (есть audit для login/role/api-key/dead-job).
- WS heartbeat/timeout — настройки заданы, активный ping/pong-цикл не реализован.

## Перед публичным SaaS
- Жёсткая изоляция арендаторов (organization_id вместо owner_user_id-seam), RBAC.
- Redis-backed RoomRegistry + горизонтальное масштабирование WS/worker.
- Полный rate limiting + WAF + квоты на загрузки/LLM.
- Ротация секретов, KMS для `ENCRYPTION_KEY`, аудит доступа к файлам.
- Антивирус/контент-проверка загружаемых файлов; вирус-скан перед обработкой.
- DLP-проверка, что транскрипты/документы не утекают в логи/Sentry (scrub уже есть — расширить).
- Подписанные/короткоживущие presigned URL + CORS-ужесточение бакета.
- Пентест, threat-model, GDPR/PII-процедуры (право на удаление, хранение).
