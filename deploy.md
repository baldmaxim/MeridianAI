# Deploy — Meridian

Portal-scoped деплой (§19): один портал = один Docker Compose project. **Сборка вне прода**, на vds только `pull` + `up`. Не трогает nginx, Keycloak, Xray, Supabase.

- Prod: <https://meridian.fvds.ru> · VPS: `ssh vds` · `/opt/portals/meridian`
- Registry: `ghcr.io/baldmaxim/meridian-{api,frontend}` (теги: `latest` + `<git-sha>`)

---

## Рабочий путь — CI/GHCR (по умолчанию)

1. Слить изменения в `main` (пути `meridian-web/backend/**`, `meridian-web/frontend/**`).
2. GitHub Actions [`build-images`](.github/workflows/deploy.yml) собирает и пушит образы в GHCR.
3. Дождаться зелёного workflow, затем на vds:

```bash
ssh vds 'cd /opt/portals/meridian && OWNER=baldmaxim TAG=latest \
  bash meridian-web/deploy/deploy-ghcr.sh'
```

`deploy-ghcr.sh`: `git pull --ff-only` → `pull api frontend` → `run --rm migrate` → `up -d --force-recreate api worker frontend edge` → health.

> Иммутабельный деплой: вместо `TAG=latest` указывай `TAG=<git-sha>` — детерминированный образ и явный откат.

---

## Проверка после деплоя

```bash
curl -fsS https://meridian.fvds.ru/health/live    # 200
curl -fsS https://meridian.fvds.ru/health/ready   # 200 (БД доступна)
ssh vds "docker compose -p meridian ps"            # все healthy
ssh vds "docker ps --format '{{.Names}}'"          # Xray/Supabase/Remnawave на месте
```

## Откат

```bash
ssh vds 'cd /opt/portals/meridian && OWNER=baldmaxim TAG=<предыдущий-git-sha> \
  bash meridian-web/deploy/deploy-ghcr.sh'
```

## Миграции БД (§8)

Применяются отдельным шагом из образа (`run --rm migrate`), под пользователем `meridian_migration`. Никаких `create_all`/ad-hoc ALTER на проде. Изменение схемы = новая Alembic-миграция.

---

## Фолбэк: локальная сборка → перенос (если CI недоступен)

Локальный Docker может быть сломан (cred-helper), на vds сборка = OOM. Если GHCR недоступен:

```bash
# dev-машина
cd meridian-web/deploy && REGISTRY=ghcr.io/baldmaxim TAG=$(git rev-parse --short HEAD) ./build.sh
docker save ghcr.io/baldmaxim/meridian-api:$TAG ghcr.io/baldmaxim/meridian-frontend:$TAG \
  | ssh vds 'docker load'
# на vds
ssh vds "cd /opt/portals/meridian/meridian-web/deploy && TAG=$TAG ./deploy.sh"
```

`deploy.sh` — health-gated с `flock`: если API не поднялся, frontend не переключается, соседи не тронуты.

## Backup / Restore (§26)

```bash
# ручной бэкап
ssh vds "docker compose -p meridian exec postgres sh -c \
  'PGPASSWORD=\$POSTGRES_PASSWORD pg_dump -U meridian meridian'" | gzip > backup.sql.gz
# restore
gunzip -c backup.sql.gz | ssh vds "docker compose -p meridian exec -T postgres psql -U meridian -d meridian"
```

Сервис `backup` делает `pg_dump | gzip` раз в сутки (хранит 7).

---

## Запрещено на проде (§19)

- `docker system prune -a`, `docker compose down --volumes`, `docker stop $(docker ps -q)`, `rm -rf /opt/portals/*`
- `git pull`/`npm install`/`build`/`vite`/`pip` на vds — только готовые образы из registry
- Обновление nginx/Keycloak в рамках portal-деплоя — отдельные infra-процедуры
- Правка `.env`/секретов в образах, коде, логах

См. также [meridian-web/deploy/README.md](meridian-web/deploy/README.md) — раскладка, ingress на FVDS, детали compose.
