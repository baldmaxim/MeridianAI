# Meridian — деплой (корп. стандарт §3, §4, §19, §26)

Portal-scoped деплой: один портал = один Docker Compose project. Ingress (nginx+TLS) — **отдельный**
инфраструктурный проект. Деплой портала НЕ трогает nginx, Keycloak и соседние сервисы на хосте.

## Структура

```
deploy/
├── build.sh                 # сборка+push образов (на dev/CI, НЕ на проде)
├── deploy-ghcr.sh           # деплой из GHCR: TAG обязателен (immutable sha, не latest)
├── deploy.sh                # деплой на VPS (pull→migrate→health-gate→up), portal-scoped
├── portal/
│   ├── docker-compose.yml   # api, worker, migrate, frontend (БД — Yandex Managed PG)
│   └── meridian.env.example # → meridian.env (НЕ в git, chmod 600)
├── backup/                  # ежедневный pg_dump на хосте: .sh + systemd .service/.timer
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

БД прод — Yandex Managed PostgreSQL 17: управляемые бэкапы делает YC (они же — PITR). Локального
postgres-контейнера и сервиса `backup` в compose нет. Дополнительно на хосте Selectel работает свой
ежедневный логический дамп (`pg_dump -Fc`) по systemd-таймеру: `backup/meridian-pg-backup.{sh,service,timer}`.

- Время: 03:30 локально (+ до 5 мин случайной задержки), `Persistent=true` — пропущенный запуск догоняется.
- Куда: `/opt/backups/meridian/meridian-<UTC>.dump` (каталог 700, файлы 600), хранится 7 последних.
- Пароль берётся из `DATABASE_URL` в `portal/meridian.env`, на экран/в логи не выводится.
- После дампа `pg_restore --list` проверяет, что в оглавлении есть объекты; иначе файл удаляется, код выхода 1.

Установка на сервере (один раз; нужны docker и python3):

```bash
cd /opt/portals/meridian/meridian-web/deploy/backup
chmod +x meridian-pg-backup.sh
sudo cp meridian-pg-backup.service meridian-pg-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now meridian-pg-backup.timer
sudo systemctl start meridian-pg-backup.service        # пробный прогон
journalctl -u meridian-pg-backup.service -n 20         # лог: "OK: <файл> <размер>, объектов: N"
systemctl list-timers meridian-pg-backup.timer
```

Другой путь к env-файлу: `Environment=ENV_FILE=...` в юните (`systemctl edit meridian-pg-backup.service`).
Путь `ExecStart` в юните — `/opt/portals/meridian/...`; если репозиторий лежит в другом месте, поправьте.

Восстановление (в **новую/чистую** БД, не поверх живой без бэкапа):

```bash
# 1. посмотреть содержимое
docker run --rm -i postgres:17-alpine pg_restore --list < /opt/backups/meridian/meridian-<UTC>.dump | head

# 2. восстановить в целевую БД (пароль — через окружение, не в аргументах)
export PGPASSWORD='<пароль>'
docker run --rm -i -e PGPASSWORD -e PGSSLMODE=require postgres:17-alpine \
  pg_restore --no-owner --no-privileges --clean --if-exists \
  -h <host> -p 6432 -U <user> -d <dbname> < /opt/backups/meridian/meridian-<UTC>.dump
unset PGPASSWORD
```

Перед деструктивными операциями на проде делайте свежий дамп вручную: `sudo systemctl start meridian-pg-backup.service`.

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
