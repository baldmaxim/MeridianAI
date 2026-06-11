-- Корп. стандарт §7: разделение прав БД.
--   meridian_migration — DDL (создаёт/меняет схему, запускает Alembic).
--   meridian_runtime   — DML (приложение в рантайме: SELECT/INSERT/UPDATE/DELETE), без DDL.
--
-- Выполняется postgres-ом ОДИН раз при инициализации пустого тома (docker-entrypoint-initdb.d),
-- от имени суперюзера POSTGRES_USER (meridian), который владеет БД.
--
-- Dev: приложение на хосте продолжает ходить под `meridian` (см. .env) — разделение не форсируется.
-- Prod: DATABASE_URL=...meridian_runtime..., MIGRATION_DATABASE_URL=...meridian_migration...
--       Пароли в проде — из secret storage (§18), НЕ дефолтные из этого файла.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'meridian_runtime') THEN
    CREATE ROLE meridian_runtime LOGIN PASSWORD 'meridian_runtime_dev' CONNECTION LIMIT 20;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'meridian_migration') THEN
    CREATE ROLE meridian_migration LOGIN PASSWORD 'meridian_migration_dev' CONNECTION LIMIT 5;
  END IF;
END
$$;

GRANT CONNECT ON DATABASE meridian TO meridian_runtime, meridian_migration;

-- migration: полный доступ к схеме (DDL)
GRANT USAGE, CREATE ON SCHEMA public TO meridian_migration;

-- runtime: только пользование схемой, без CREATE
GRANT USAGE ON SCHEMA public TO meridian_runtime;

-- Таблицы создаются миграциями ПОЗЖЕ. Чтобы runtime автоматически получал DML на них,
-- задаём DEFAULT PRIVILEGES для обеих ролей, которыми реально могут запускаться миграции:
--   - meridian_migration (прод),
--   - meridian (dev-фолбэк: миграции под суперюзером).
ALTER DEFAULT PRIVILEGES FOR ROLE meridian_migration IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO meridian_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE meridian_migration IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO meridian_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE meridian IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO meridian_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE meridian IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO meridian_runtime;
