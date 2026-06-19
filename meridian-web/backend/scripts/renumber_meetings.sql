-- РАЗОВАЯ перенумерация встреч: удалить пустые черновики и пронумеровать оставшиеся 1..N
-- по времени начала. Номер встречи в UI = meeting_sessions.id, поэтому правим именно id
-- с аккуратным переносом ВСЕХ внешних ключей.
--
-- ⚠️  ПЕРЕД ЗАПУСКОМ ОБЯЗАТЕЛЬНО снять бэкап:  pg_dump "$DATABASE_URL" > backup.sql
-- ⚠️  Это НЕ Alembic-миграция (привязано к текущему снапшоту данных, не воспроизводимо
--     между окружениями). Держим в scripts/, запускаем вручную ОДИН раз.
-- Запуск под DDL-ролью (meridian_migration):  psql "$MIGRATION_DATABASE_URL" -f renumber_meetings.sql
--
-- Порядок: СНАЧАЛА выкатить фикс (перестают создаваться пустые черновики), ПОТОМ этот скрипт.
--
-- Как работает перенос id без ON UPDATE CASCADE:
--   * FK на meeting_sessions(id) временно делаются DEFERRABLE → проверка ссылок откладывается
--     до COMMIT, поэтому parent и дети можно переписывать в любом порядке;
--   * перенумерация в две фазы через отрицательные id (старые до 28, новые 1..N) — это
--     исключает коллизии PK во время UPDATE (отрицательных id ни у кого нет);
--   * в конце FK возвращаются в NOT DEFERRABLE, sequence сбрасывается на MAX(id)+1.

\set ON_ERROR_STOP on

-- ===== Диагностика ДО =====
SELECT 'before' AS phase, count(*) AS total, min(id) AS min_id, max(id) AS max_id
FROM meeting_sessions;

BEGIN;

-- 1) Удалить «пустые» встречи: ни одной дочерней записи НИ В ОДНОЙ ссылающейся
--    таблице И пусты все смысловые поля. Реальные встречи (сегменты / подсказки /
--    документы / протокол / участники / контекст / темы / коррекции и т.п.) под
--    условие не попадают. Дети реальных встреч удаляются по ON DELETE CASCADE, но
--    сюда они не доходят (guard ниже). learning_candidates.meeting_id → ON DELETE
--    SET NULL, но наличие кандидата = встреча дала контент → тоже считаем непустой.

-- 1a) Множество встреч, на которые ссылается хоть один дочерний FK (динамически по
--     pg_constraint — покрывает все текущие и будущие дочерние таблицы без хардкода).
CREATE TEMP TABLE _referenced ON COMMIT DROP AS SELECT id FROM meeting_sessions WHERE false;
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT ns.nspname AS schema_name, rel.relname AS table_name, att.attname AS col_name
    FROM pg_constraint con
    JOIN pg_class rel    ON rel.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = rel.relnamespace
    JOIN unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k.attnum
    WHERE con.contype = 'f'
      AND con.confrelid = 'meeting_sessions'::regclass
  LOOP
    EXECUTE format('INSERT INTO _referenced SELECT DISTINCT %I FROM %I.%I WHERE %I IS NOT NULL',
                   r.col_name, r.schema_name, r.table_name, r.col_name);
  END LOOP;
END $$;

-- 1b) Удалить только по-настоящему пустые черновики (NOT EXISTS, безопасно к NULL).
DELETE FROM meeting_sessions ms
WHERE ms.title IS NULL
  AND ms.meeting_topic IS NULL
  AND ms.meeting_notes IS NULL
  AND ms.negotiation_type IS NULL
  AND ms.meeting_role IS NULL
  AND ms.opponent_weaknesses IS NULL
  AND ms.customer_id IS NULL
  AND ms.object_id IS NULL
  AND ms.protocol_markdown IS NULL
  AND ms.protocol_json IS NULL
  AND ms.summary_json IS NULL
  AND ms.micro_summary IS NULL
  AND ms.tags_json IS NULL
  AND ms.audio_path IS NULL
  AND ms.ended_at IS NULL
  AND COALESCE(ms.recorded_seconds, 0) = 0
  AND NOT EXISTS (SELECT 1 FROM _referenced r WHERE r.id = ms.id);

-- 2) Перенумеровать оставшиеся в 1..N (по started_at), перенося все FK.
DO $$
DECLARE
  r   record;
  seq text;
BEGIN
  -- 2a) Сделать все FK на meeting_sessions(id) откладываемыми
  FOR r IN
    SELECT con.conname, ns.nspname AS schema_name, rel.relname AS table_name
    FROM pg_constraint con
    JOIN pg_class rel    ON rel.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = rel.relnamespace
    WHERE con.contype = 'f'
      AND con.confrelid = 'meeting_sessions'::regclass
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ALTER CONSTRAINT %I DEFERRABLE INITIALLY IMMEDIATE',
                   r.schema_name, r.table_name, r.conname);
  END LOOP;

  SET CONSTRAINTS ALL DEFERRED;

  -- 2b) Карта старый id → новый id (1..N по времени начала)
  CREATE TEMP TABLE _mid_map ON COMMIT DROP AS
    SELECT id AS old_id, row_number() OVER (ORDER BY started_at, id)::int AS new_id
    FROM meeting_sessions;

  IF NOT EXISTS (SELECT 1 FROM _mid_map WHERE old_id <> new_id) THEN
    RAISE NOTICE 'meeting ids уже плотные 1..N — перенумерация не требуется';
  ELSE
    -- 2c) ФАЗА A: дети → -(new_id), затем parent → -(new_id)
    FOR r IN
      SELECT ns.nspname AS schema_name, rel.relname AS table_name, att.attname AS col_name
      FROM pg_constraint con
      JOIN pg_class rel    ON rel.oid = con.conrelid
      JOIN pg_namespace ns ON ns.oid = rel.relnamespace
      JOIN unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
      JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k.attnum
      WHERE con.contype = 'f'
        AND con.confrelid = 'meeting_sessions'::regclass
    LOOP
      EXECUTE format('UPDATE %I.%I c SET %I = -m.new_id FROM _mid_map m WHERE c.%I = m.old_id',
                     r.schema_name, r.table_name, r.col_name, r.col_name);
    END LOOP;

    UPDATE meeting_sessions s SET id = -m.new_id FROM _mid_map m WHERE s.id = m.old_id;

    -- 2d) ФАЗА B: вернуть в положительные (дети + parent)
    FOR r IN
      SELECT ns.nspname AS schema_name, rel.relname AS table_name, att.attname AS col_name
      FROM pg_constraint con
      JOIN pg_class rel    ON rel.oid = con.conrelid
      JOIN pg_namespace ns ON ns.oid = rel.relnamespace
      JOIN unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
      JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k.attnum
      WHERE con.contype = 'f'
        AND con.confrelid = 'meeting_sessions'::regclass
    LOOP
      EXECUTE format('UPDATE %I.%I c SET %I = -c.%I WHERE c.%I < 0',
                     r.schema_name, r.table_name, r.col_name, r.col_name, r.col_name);
    END LOOP;

    UPDATE meeting_sessions SET id = -id WHERE id < 0;
  END IF;

  -- 2e) Сбросить счётчик id на MAX(id)+1 (следующая встреча продолжит без дыр)
  seq := pg_get_serial_sequence('meeting_sessions', 'id');
  IF seq IS NOT NULL THEN
    PERFORM setval(seq, COALESCE((SELECT max(id) FROM meeting_sessions), 0) + 1, false);
  ELSE
    EXECUTE format('ALTER TABLE meeting_sessions ALTER COLUMN id RESTART WITH %s',
                   COALESCE((SELECT max(id) FROM meeting_sessions), 0) + 1);
  END IF;
END $$;

-- 3) Вернуть FK в NOT DEFERRABLE (исходное состояние схемы)
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT con.conname, ns.nspname AS schema_name, rel.relname AS table_name
    FROM pg_constraint con
    JOIN pg_class rel    ON rel.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = rel.relnamespace
    WHERE con.contype = 'f'
      AND con.confrelid = 'meeting_sessions'::regclass
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ALTER CONSTRAINT %I NOT DEFERRABLE',
                   r.schema_name, r.table_name, r.conname);
  END LOOP;
END $$;

-- ===== Диагностика ПОСЛЕ (проверить перед COMMIT; при сомнении — ROLLBACK) =====
SELECT 'after' AS phase, count(*) AS total, min(id) AS min_id, max(id) AS max_id
FROM meeting_sessions;
SELECT id, started_at, title FROM meeting_sessions ORDER BY id;

COMMIT;
