# Meridian — деплой (корп. стандарт §3, §4, §19, §26)

Portal-scoped деплой: один портал = один Docker Compose project. Ingress (nginx+TLS) — **отдельный**
инфраструктурный проект. Деплой портала НЕ трогает nginx, Keycloak и соседние сервисы на хосте.

## Структура

```
deploy/
├── build.sh                 # сборка+push образов (на dev/CI, НЕ на проде)
├── deploy.sh                # деплой на VPS (pull→migrate→health-gate→up), portal-scoped
├── portal/
│   ├── docker-compose.yml   # api, (worker — фаза 4), migrate, postgres, backup, frontend
│   └── meridian.env.example # → meridian.env (НЕ в git, chmod 600)
└── infra-nginx/             # ingress: nginx + certbot (только если нет общего nginx — см. ниже)
    ├── docker-compose.yml
    ├── nginx.conf
    └── conf.d/meridian.conf
```

На VPS:
```
/opt/portals/app/        ← portal/* + meridian.env
/opt/infra/nginx/        ← infra-nginx/* (или существующий общий nginx)
```

## Раскладка (первый раз)

```bash
# 1. общая сеть для ingress ↔ порталы
docker network create infra_web

# 2. образы (на dev/CI)
REGISTRY=ghcr.io/<owner> TAG=$(git rev-parse --short HEAD) ./build.sh

# 3. на VPS: /opt/portals/app/meridian.env (из примера), chmod 600
# 4. деплой
TAG=<git-sha> ./deploy.sh
```

## Ingress на хосте — важно (no-neighbor-damage, §19)

На текущем VPS :443 уже занят nginx, фронтящим соседние сервисы на хосте. Два варианта:

- **A (рекомендуется на этом хосте):** НЕ поднимать `infra-nginx`. Внести `infra-nginx/conf.d/meridian.conf`
  в существующий nginx и подключить его контейнер к сети `infra_web`
  (`docker network connect infra_web <nginx>`). Так Meridian не конкурирует за :443 и не задевает соседние сервисы на хосте.
- **B (Yandex/greenfield):** поднять `infra-nginx` как единый ingress:
  `cd /opt/infra/nginx && docker compose up -d`. Сертификат — `init-letsencrypt`-флоу (см. корень).

upstream-имена nginx (`meridian-api`, `meridian-frontend`) = сетевые алиасы из `portal/docker-compose.yml`.

## Обновление версии

```bash
REGISTRY=... TAG=<new-sha> ./build.sh      # dev/CI
TAG=<new-sha> ./deploy.sh                   # VPS — health-gated, откат = прошлый TAG
```
Откат: `TAG=<предыдущий-sha> ./deploy.sh`.

## Backup / Restore (§26)

Бэкап: сервис `backup` делает `pg_dump | gzip` раз в сутки в том `pg_backups` (хранит 7).
В фазе 5 — выгрузка в S3.

```bash
# ручной бэкап
docker compose -p meridian exec postgres sh -c 'PGPASSWORD=$POSTGRES_PASSWORD pg_dump -U meridian meridian' | gzip > backup.sql.gz

# restore в чистую БД
gunzip -c backup.sql.gz | docker compose -p meridian exec -T postgres psql -U meridian -d meridian
```

## Запрещено на проде (§19)

- `docker system prune -a`, `docker compose down --volumes`, `docker stop $(docker ps -q)`, `rm -rf /opt/portals/*`
- `git pull` / `npm install` / `build` на VPS — только готовые образы из registry
- обновление nginx/Keycloak в рамках portal-деплоя — это отдельные infra-процедуры

## Проверка после деплоя

```bash
curl -fsS https://app.example.com/health/live      # 200
curl -fsS https://app.example.com/health/ready     # 200 (БД доступна)
docker compose -p meridian ps                        # все healthy
# соседи не задеты:
docker ps --format '{{.Names}}'                      # соседние сервисы на хосте на месте
```
