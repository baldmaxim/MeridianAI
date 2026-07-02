# Data Retention Inventory (Этап 25)

Инвентаризация данных ОДНОЙ встречи для privacy/retention controls. Основа для export/delete-plan.

| Категория | Где хранится (table/backend) | Scope | Удаляемо по meeting_id | Export v1 | Delete v1 | Shared-риск / примечание |
|---|---|---|---|---|---|---|
| meeting core | `meeting_sessions` (db) | meeting | да (сама запись) | да (метаданные+текст) | text-wipe / полное удаление опц. | содержит protocol/summary/notes/ai_settings_snapshot_json |
| transcript | `transcript_segments`, `meeting_multi_channel_segments`, `meeting_transcription_epochs` (db, CASCADE) | meeting | да | да (текст) | да | raw text |
| saved exports | `saved_transcriptions` (db, CASCADE) | meeting | да | нет | да | file-refs only |
| summary/protocol | `meeting_sessions` cols + `meeting_decisions/action_items/risks/open_questions`, `meeting_conversation_topics` (CASCADE) | meeting | да | да | да | LLM-текст |
| suggestions/cards | `meeting_suggestions` (db, CASCADE) | meeting | да | да | да | card_json |
| speaker roles | `meeting_speaker_roles`, `meeting_speaker_segment_corrections` (CASCADE) | meeting | да | да (labels/sides) | да | не PII |
| speaker_identity_hints | внутри `meeting_sessions.ai_settings_snapshot_json` | meeting | да (очистка snapshot) | нет | да (text-wipe) | без PII |
| documents (link) | `meeting_documents` (db, CASCADE) | meeting | да (link) | метаданные | да (detach) | сам документ — shared |
| documents (record) | `documents` + `document_chunks` (db+S3) | **user/shared** | только если привязан к 1 встрече | метаданные | да если не shared, иначе skip | **shared_reference** — может быть в др. встречах |
| audio (meeting) | `files` (purpose=meeting_audio, S3) + `meeting_sessions.audio_path` (local) | meeting (SET NULL) | да (explicit) | метаданные | да (S3 delete + local guard) | raw audio в S3 |
| audio (batch) | `batch_jobs` (db, SET NULL) | user (meeting_id link) | да (explicit) | нет | да (execute) | transcription_text/protocol |
| jobs/outbox | `jobs` (db, payload.meeting_id) | глобально | да (по payload) | нет | cancel (status=dead) | payload JSON |
| learning | `learning_candidates` (db, SET NULL) | **user** | да (по meeting_id) | нет | да (кандидаты встречи) | одобренные знания живут в отдельных user-таблицах (glossary/playbooks) — НЕ удаляются |
| storage objects | S3 (meeting_audio + meeting-scoped docs) | mixed | да (explicit) | нет | idempotent S3 delete | safe_ref только |
| traces/diagnostics | **app.log только** (не в БД) | external | нет | нет | нет (logrotate) | приложением не управляется |

## SET NULL — требуют явного удаления
`learning_candidates`, `files`, `batch_jobs` при удалении встречи получают `meeting_id=NULL` (не CASCADE)
→ delete-сервис удаляет их явно по `meeting_id`.

## Inventory totals (Этап 26)

`participant`, `meeting_context` (meeting_context_sources), `saved_transcription`,
`ai_settings_snapshot` — отдельные категории и попадают в `totals` inventory-отчёта (раньше
participants/context не агрегировались). Значения — только counts/наличие, без raw (имена участников,
значения hints, текст не выводятся).

## Не управляется приложением
- Диагностические traces (SIGNAL/PER_CHANNEL_STT/SOURCE_RECONCILE) пишутся только в `app.log` → ротация
  логов на стороне инфраструктуры (logrotate), не через privacy API.
- Внешние копии (backup БД, S3 versioning, реплики) — вне контура приложения.
