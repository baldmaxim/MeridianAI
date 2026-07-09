#!/usr/bin/env bash
# Деплой Meridian на выделенный сервер из GHCR: pull готовых образов + migrate + up.
# БЕЗ сборки на сервере (§19). Ingress — отдельный проект infra-nginx (TLS :80/:443).
# Образы собирает GitHub Actions. Запуск НА сервере или через:
#   ssh "$DEPLOY_SSH" 'OWNER=your-org TAG=<git-sha> bash ${REMOTE_DIR:-/opt/portals/app}/meridian-web/deploy/deploy-ghcr.sh'
#
#   OWNER=your-org TAG=<git-sha> bash deploy-ghcr.sh
#   (приватные пакеты: задать GHCR_USER + GHCR_TOKEN для docker login)
set -euo pipefail

OWNER="${OWNER:-your-org}"
TAG="${TAG:-latest}"
REMOTE_DIR="${REMOTE_DIR:-/opt/portals/app}"
INFRA_DIR="${INFRA_DIR:-/opt/infra/nginx}"
DOMAIN="${DOMAIN:-app.example.com}"
export REGISTRY="ghcr.io/$OWNER"
export TAG

cd "$REMOTE_DIR"
git pull --ff-only

if [ -n "${GHCR_TOKEN:-}" ]; then
  echo "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER:-$OWNER}" --password-stdin
fi

DC="docker compose -p meridian --env-file meridian-web/deploy/portal/meridian.env -f meridian-web/deploy/portal/docker-compose.yml"

echo "== pull образов из GHCR (${REGISTRY} @ ${TAG}) =="
$DC pull api frontend

echo "== миграции (отдельный шаг, из образа) =="
$DC run --rm migrate

echo "== up app-сервисов (пересоздаются при смене образа/конфига) =="
$DC up -d api worker frontend

echo "== health-gate: ждём ready (внутренняя проверка, до 90с) =="
ok=0
for _ in $(seq 1 30); do
  if $DC exec -T api python -c \
      "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready').status==200 else 1)" 2>/dev/null; then
    ok=1; break
  fi
  sleep 3
done
if [ "$ok" != 1 ]; then
  echo "API НЕ healthy — ABORT. Логи:"; $DC logs --tail=50 api || true; exit 1
fi

echo "== очистка старых образов Meridian (оставляем текущий TAG + ${KEEP_RECENT:-2} последних) =="
prune_old_images() {
  local repo="$1" keep="${KEEP_RECENT:-2}"
  local cur; cur="$(docker images -q "$repo:$TAG" | head -1)"
  # ID по убыванию даты создания, без дублей, без текущего тега; удаляем всё после первых $keep
  docker images "$repo" --format '{{.CreatedAt}}\t{{.ID}}' \
    | sort -r | awk '{print $NF}' | awk '!seen[$0]++' \
    | { [ -n "$cur" ] && grep -v "^${cur}$" || cat; } \
    | tail -n +"$((keep + 1))" \
    | xargs -r docker rmi 2>/dev/null || true
}
prune_old_images "$REGISTRY/meridian-api"
prune_old_images "$REGISTRY/meridian-frontend"
docker image prune -f >/dev/null 2>&1 || true
df -h / | awk 'NR==1 || /\/$/ {print}'

echo "== ingress infra-nginx: reload (resolver сам переразрешает IP; reload нужен лишь при смене meridian.conf) =="
if [ -d "$INFRA_DIR" ]; then
  ( cd "$INFRA_DIR" && docker compose exec -T nginx nginx -t && docker compose exec -T nginx nginx -s reload ) \
    || echo "(reload infra-nginx пропущен — проверьте, что проект поднят)"
fi

$DC ps --format 'table {{.Name}}\t{{.Status}}'
echo "== external health =="
echo "live=$(curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN/health/live) ready=$(curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN/health/ready)"
echo "== готово (${REGISTRY}/meridian-*:${TAG}) =="
