#!/usr/bin/env bash
# Деплой на vds из GHCR: pull готовых образов + migrate + up. БЕЗ сборки на vds (§19).
# Запускается НА vds (или через ssh vds 'bash ...'). Образы собирает GitHub Actions.
#
#   OWNER=baldmaxim TAG=latest bash deploy-ghcr.sh
#   (приватные пакеты: задать GHCR_USER + GHCR_TOKEN для docker login)
set -euo pipefail

OWNER="${OWNER:-baldmaxim}"
TAG="${TAG:-latest}"
REMOTE_DIR="${REMOTE_DIR:-/opt/portals/meridian}"
export API_IMAGE="ghcr.io/$OWNER/meridian-api:$TAG"
export FRONTEND_IMAGE="ghcr.io/$OWNER/meridian-frontend:$TAG"

cd "$REMOTE_DIR"
git pull --ff-only

if [ -n "${GHCR_TOKEN:-}" ]; then
  echo "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER:-$OWNER}" --password-stdin
fi

DC="docker compose -p meridian --env-file meridian-web/deploy/portal/meridian.env -f meridian-web/deploy/portal/docker-compose.fvds.yml"

echo "== pull образов из GHCR =="
$DC pull api frontend

echo "== миграции (из образа) =="
$DC run --rm migrate

echo "== рестарт сервисов (без сборки) =="
$DC up -d --force-recreate api worker frontend edge
$DC ps --format 'table {{.Name}}\t{{.Status}}'

echo "== health =="
echo "live=$(curl -s -o /dev/null -w '%{http_code}' https://meridian.fvds.ru/health/live) ready=$(curl -s -o /dev/null -w '%{http_code}' https://meridian.fvds.ru/health/ready)"
