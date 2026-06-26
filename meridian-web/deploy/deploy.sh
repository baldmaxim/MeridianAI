#!/usr/bin/env bash
# Portal-scoped деплой Meridian (корп. стандарт §19). Запускать на VPS в ${REMOTE_DIR:-/opt/portals/app}.
#
# Гарантии:
#  - НЕ трогает ingress-nginx и другие сервисы, работающие на этом хосте (§19, no-neighbor-damage).
#  - Образы только из registry с immutable-тегом (никаких build/git pull/npm на проде).
#  - Миграции — отдельным шагом, под migration-пользователем (§8).
#  - Health-gate: если API не поднялся — деплой прерывается, frontend не переключается.
#  - НИКОГДА не выполняет: docker system prune -a, compose down --volumes, docker stop $(docker ps -q).
set -euo pipefail

cd "$(dirname "$0")/portal"
: "${TAG:?set TAG (git sha) — образ ${REGISTRY}/meridian-api:TAG}"
export TAG

log() { echo "[deploy $(date +%H:%M:%S)] $*"; }

log "1/6 deployment lock"
exec 9>/tmp/meridian-deploy.lock
flock -n 9 || { echo "другой деплой уже идёт — выход"; exit 1; }

log "2/6 pull images (${TAG})"
docker compose pull api frontend

log "3/6 migrations (one-shot, против Yandex Managed PG)"
docker compose run --rm migrate

log "4/6 start api + worker"
docker compose up -d api worker

log "5/6 health gate (/health/ready)"
ok=0
for _ in $(seq 1 30); do
  if docker compose exec -T api python -c \
      "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready').status==200 else 1)" 2>/dev/null; then
    ok=1; break
  fi
  sleep 3
done
if [ "$ok" != 1 ]; then
  echo "API НЕ healthy — ABORT. frontend не переключён, соседи не тронуты."
  docker compose logs --tail=40 api || true
  exit 1
fi

log "6/6 start frontend"
docker compose up -d frontend

echo "==================== deployment report ===================="
echo "  tag:    ${TAG}"
echo "  health: ready"
docker compose ps
echo "==========================================================="
log "DONE"
