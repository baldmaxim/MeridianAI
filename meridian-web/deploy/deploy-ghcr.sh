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

echo "== рестарт app-сервисов (edge НЕ пересоздаём: он переразрешает api/frontend по DNS, TTL 10s) =="
$DC up -d --no-recreate edge          # гарантируем, что edge поднят; existing-контейнер не трогаем
$DC up -d api worker frontend         # пересоздаются только при смене образа (TAG) или env/конфига

echo "== ждём готовности api (до 60с) — чтобы не закрыть деплой на окне прогрева =="
ready=""
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' https://meridian.fvds.ru/health/ready || true)
  if [ "$code" = "200" ]; then ready=1; break; fi
  sleep 2
done

echo "== reload edge (применить возможные изменения edge-nginx.conf + свежий DNS, без обрыва соединений) =="
$DC exec -T edge nginx -t && $DC exec -T edge nginx -s reload || echo "(edge reload пропущен — проверьте конфиг)"

$DC ps --format 'table {{.Name}}\t{{.Status}}'
echo "== health =="
echo "live=$(curl -s -o /dev/null -w '%{http_code}' https://meridian.fvds.ru/health/live) ready=$(curl -s -o /dev/null -w '%{http_code}' https://meridian.fvds.ru/health/ready)"
[ -n "$ready" ] || echo "ВНИМАНИЕ: api не отдал ready=200 за 60с — смотрите: $DC logs --tail=50 api"
