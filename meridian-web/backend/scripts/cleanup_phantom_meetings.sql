-- Очистка «пустых» встреч, появившихся от захода на портал (а не от реальной работы).
-- Безопасно для dev и prod: трогает только draft без контента и без контекста,
-- старше 15 минут (чтобы не задеть только что открытую живую сессию).
-- Дочерние записи (participants/segments/suggestions/documents/protocol/conversation)
-- удаляются по ON DELETE CASCADE; knowledge.meeting_id -> NULL.
--
-- Порядок: СНАЧАЛА задеплоить фикс (перестают создаваться новые), ПОТОМ прогнать этот скрипт.
-- Запуск (внутри Postgres-контейнера): psql "$DATABASE_URL" -f cleanup_phantom_meetings.sql
-- Это DML (DELETE) — отдельная Alembic-миграция не нужна.

\set ON_ERROR_STOP on

BEGIN;

-- 1) Диагностика: сколько строк будет удалено
SELECT count(*) AS phantom_count
FROM meeting_sessions ms
WHERE ms.is_active = true
  AND ms.title IS NULL
  AND ms.meeting_topic IS NULL
  AND ms.meeting_notes IS NULL
  AND ms.customer_id IS NULL
  AND ms.object_id IS NULL
  AND ms.protocol_markdown IS NULL
  AND ms.started_at < (now() - interval '15 minutes')
  AND NOT EXISTS (SELECT 1 FROM transcript_segments s WHERE s.session_id = ms.id)
  AND NOT EXISTS (SELECT 1 FROM meeting_suggestions g WHERE g.session_id = ms.id)
  AND NOT EXISTS (SELECT 1 FROM meeting_documents d WHERE d.session_id = ms.id);

-- 2) Удаление пустышек
DELETE FROM meeting_sessions ms
WHERE ms.is_active = true
  AND ms.title IS NULL
  AND ms.meeting_topic IS NULL
  AND ms.meeting_notes IS NULL
  AND ms.customer_id IS NULL
  AND ms.object_id IS NULL
  AND ms.protocol_markdown IS NULL
  AND ms.started_at < (now() - interval '15 minutes')
  AND NOT EXISTS (SELECT 1 FROM transcript_segments s WHERE s.session_id = ms.id)
  AND NOT EXISTS (SELECT 1 FROM meeting_suggestions g WHERE g.session_id = ms.id)
  AND NOT EXISTS (SELECT 1 FROM meeting_documents d WHERE d.session_id = ms.id);

-- Проверить вывод DELETE перед COMMIT. Если что-то не так — ROLLBACK вместо COMMIT.
COMMIT;
