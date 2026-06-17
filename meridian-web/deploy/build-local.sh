#!/usr/bin/env bash
# Сборка ЛОКАЛЬНО → выкладка на vds (корп. стандарт §19; правило «сначала собрать локально, потом выложить»).
# vds (1.8 GiB RAM + соседи Remnawave/Supabase/VPN) НЕ собирает — только грузит готовые образы и поднимает.
# Запускать на dev-машине в ИНТЕРАКТИВНОМ терминале (где Docker может тянуть базовые образы).
#
#   bash meridian-web/deploy/build-local.sh
#
# Переменные: SSH (алиас, по умолч. vds), REMOTE_DIR (по умолч. /opt/portals/meridian).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"            # meridian-web/
SSH="${SSH:-vds}"
REMOTE_DIR="${REMOTE_DIR:-/opt/portals/meridian}"
DC="docker compose -p meridian --env-file meridian-web/deploy/portal/meridian.env -f meridian-web/deploy/portal/docker-compose.fvds.yml"

echo "== 0/6 git pull (локально) =="
git pull --ff-only

echo "== 1/6 build образов ЛОКАЛЬНО =="
docker build -t meridian-api:local "$ROOT/backend"
docker build -t meridian-frontend:local "$ROOT/frontend"

echo "== 2/6 синк конфигов/миграций на vds (git pull — только текст, не build) =="
ssh "$SSH" "cd $REMOTE_DIR && git pull --ff-only"

echo "== 3/6 перенос образов на vds (docker save | ssh docker load) =="
docker save meridian-api:local meridian-frontend:local | gzip | ssh "$SSH" 'gunzip | docker load'

echo "== 4/6 миграции (отдельный шаг, из образа) =="
ssh "$SSH" "cd $REMOTE_DIR && $DC run --rm migrate"

echo "== 5/6 рестарт сервисов БЕЗ сборки на vds =="
ssh "$SSH" "cd $REMOTE_DIR && $DC up -d --force-recreate api worker frontend edge && $DC ps --format 'table {{.Name}}\t{{.Status}}'"

echo "== 6/6 health =="
ssh "$SSH" 'echo live=$(curl -s -o /dev/null -w "%{http_code}" https://meridian.fvds.ru/health/live) ready=$(curl -s -o /dev/null -w "%{http_code}" https://meridian.fvds.ru/health/ready)'
echo "== готово =="
