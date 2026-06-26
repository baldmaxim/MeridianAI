#!/usr/bin/env bash
# Сборка + push immutable-образов (§19: build вне prod VPS, на dev/CI).
set -euo pipefail

: "${REGISTRY:?set REGISTRY, напр. ghcr.io/<owner>}"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # meridian-web/

echo "Building meridian-api:${TAG} / meridian-frontend:${TAG}"
docker build -t "${REGISTRY}/meridian-api:${TAG}"      "${ROOT}/backend"
docker build -t "${REGISTRY}/meridian-frontend:${TAG}" "${ROOT}/frontend"

docker push "${REGISTRY}/meridian-api:${TAG}"
docker push "${REGISTRY}/meridian-frontend:${TAG}"
echo "Pushed ${REGISTRY}/*:${TAG}"
echo "Деплой:  TAG=${TAG} ./deploy.sh   (на VPS, в \${REMOTE_DIR:-/opt/portals/app})"
