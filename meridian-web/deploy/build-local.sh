#!/usr/bin/env bash
# Сборка ЛОКАЛЬНО → выкладка на сервер (fallback, если CI/GHCR недоступен; §19: на сервере НЕ собирать).
# Канонический путь — GHCR (deploy-ghcr.sh). Этот скрипт грузит локально собранные образы (save|load)
# под теги, которые ждёт registry-compose docker-compose.yml. Ingress — отдельный infra-nginx.
#
#   bash meridian-web/deploy/build-local.sh
#
# Переменные: DEPLOY_SSH (ssh-алиас сервера, по умолч. your-server),
#             REMOTE_DIR (/opt/portals/app), DOMAIN (app.example.com).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"            # meridian-web/
DEPLOY_SSH="${DEPLOY_SSH:-your-server}"
REMOTE_DIR="${REMOTE_DIR:-/opt/portals/app}"
DOMAIN="${DOMAIN:-app.example.com}"
REG="local"; TAG="dev"
DC="REGISTRY=$REG TAG=$TAG docker compose -p meridian --env-file meridian-web/deploy/portal/meridian.env -f meridian-web/deploy/portal/docker-compose.yml"

echo "== 0/6 git pull (локально) =="
git pull --ff-only

echo "== 1/6 build образов ЛОКАЛЬНО (теги под docker-compose.yml: $REG/meridian-*:$TAG) =="
docker build -t "$REG/meridian-api:$TAG" "$ROOT/backend"
docker build -t "$REG/meridian-frontend:$TAG" "$ROOT/frontend"

echo "== 2/6 синк конфигов/миграций на сервер (git pull — только текст, не build) =="
ssh "$DEPLOY_SSH" "cd $REMOTE_DIR && git pull --ff-only"

echo "== 3/6 перенос образов (docker save | ssh docker load) =="
docker save "$REG/meridian-api:$TAG" "$REG/meridian-frontend:$TAG" | gzip | ssh "$DEPLOY_SSH" 'gunzip | docker load'

echo "== 4/6 миграции (отдельный шаг, из образа) =="
ssh "$DEPLOY_SSH" "cd $REMOTE_DIR && $DC run --rm migrate"

echo "== 5/6 up сервисов БЕЗ сборки на сервере =="
ssh "$DEPLOY_SSH" "cd $REMOTE_DIR && $DC up -d api worker frontend && $DC ps --format 'table {{.Name}}\t{{.Status}}'"

echo "== 6/6 health =="
ssh "$DEPLOY_SSH" "echo live=\$(curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN/health/live) ready=\$(curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN/health/ready)"
echo "== готово =="
