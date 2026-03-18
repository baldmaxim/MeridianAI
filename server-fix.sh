#!/usr/bin/env bash
# =============================================================================
# server-fix.sh — Исправление веб-архитектуры сервера
# Запуск: sudo bash server-fix.sh
#
# Что делает:
#   1. Фиксит docker-compose AI Helper (убирает конфликт портов 80/443)
#   2. Фиксит system nginx (убирает listen 443 из odintsovlive)
#   3. Запускает всё в правильном порядке
#
# Что НЕ трогает:
#   - Xray (порт 443)
#   - Supabase / Kong (порт 8000)
#   - .env файлы
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

log()  { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; exit 1; }
section() { echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}"; }

[[ $EUID -ne 0 ]] && err "Запускай от root: sudo bash $0"

BACKUP_SUFFIX="bak.$(date +%Y%m%d_%H%M%S)"
AI_HELPER_DIR="/opt/ai-helper"

# Предварительные проверки
[ -d "$AI_HELPER_DIR" ] || err "Директория $AI_HELPER_DIR не найдена"
systemctl is-active xray >/dev/null 2>&1 || err "Xray не запущен! Отмена."

# =========================================================================
section "ФАЗА 1: Бэкапы"
# =========================================================================

cp "$AI_HELPER_DIR/docker-compose.yml" "$AI_HELPER_DIR/docker-compose.yml.$BACKUP_SUFFIX"
log "Бэкап docker-compose.yml"

cp "$AI_HELPER_DIR/nginx/nginx.conf" "$AI_HELPER_DIR/nginx/nginx.conf.$BACKUP_SUFFIX"
log "Бэкап docker nginx.conf"

cp -r /etc/nginx "/etc/nginx.$BACKUP_SUFFIX"
log "Бэкап /etc/nginx → /etc/nginx.$BACKUP_SUFFIX"

# =========================================================================
section "ФАЗА 2: Фикс Docker AI Helper"
# =========================================================================

# --- 2.1. Новый docker-compose.yml ---
cat > "$AI_HELPER_DIR/docker-compose.yml" <<'COMPOSE'
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ai_helper
      POSTGRES_USER: ai_helper
      POSTGRES_PASSWORD: ${DB_PASSWORD:-ai_helper_dev}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ai_helper"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  backend:
    build: ./backend
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://ai_helper:${DB_PASSWORD:-ai_helper_dev}@postgres/ai_helper
      JWT_SECRET: ${JWT_SECRET:-dev-secret-change-in-prod}
      ENCRYPTION_KEY: ${ENCRYPTION_KEY:-}
      UPLOAD_DIR: /app/uploads
      TRANSCRIPTION_DIR: /app/transcriptions
    volumes:
      - uploads:/app/uploads
      - transcriptions:/app/transcriptions
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

  frontend:
    build: ./frontend
    depends_on:
      - backend
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "127.0.0.1:8080:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - backend
      - frontend
    restart: unless-stopped

volumes:
  postgres_data:
  uploads:
  transcriptions:
COMPOSE
log "docker-compose.yml обновлён (nginx → 127.0.0.1:8080, certbot удалён)"

# --- 2.2. Новый docker nginx.conf (HTTP only) ---
cat > "$AI_HELPER_DIR/nginx/nginx.conf" <<'NGINX'
events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    upstream backend {
        server backend:8000;
    }

    upstream frontend {
        server frontend:80;
    }

    server {
        listen 80;
        server_name _;

        client_max_body_size 50M;

        # REST API
        location /api/ {
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # WebSocket
        location /ws/ {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }

        # Frontend (SPA)
        location / {
            proxy_pass http://frontend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
NGINX
log "docker nginx.conf обновлён (HTTP only, без SSL)"

# --- 2.3. Пересобрать и перезапустить ---
section "Перезапуск Docker AI Helper"
cd "$AI_HELPER_DIR"

echo "Останавливаю контейнеры..."
docker compose down 2>&1 | tail -5
log "docker compose down"

echo "Запускаю контейнеры..."
docker compose up -d --build 2>&1 | tail -10
log "docker compose up -d --build"

# Ждём пока nginx контейнер стартует
echo "Жду запуска контейнеров (10 сек)..."
sleep 10

# --- 2.4. Проверка Docker ---
section "Проверка Docker"

echo "Контейнеры:"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep ai-helper || warn "ai-helper контейнеры не найдены"

if ss -tlnp | grep -q ':8080'; then
    log "Порт 8080 слушает"
    RESP=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null || echo "ERR")
    log "curl http://127.0.0.1:8080/ → HTTP $RESP"
else
    warn "Порт 8080 НЕ слушает — docker nginx возможно ещё стартует"
fi

# Проверить что xray жив
if systemctl is-active xray >/dev/null 2>&1; then
    log "Xray по-прежнему работает"
else
    err "XRAY УПАЛ! Проверь вручную: systemctl status xray"
fi

# =========================================================================
section "ФАЗА 3: Фикс System Nginx"
# =========================================================================

# --- 3.1. Убрать default из sites-enabled (если есть) ---
rm -f /etc/nginx/sites-enabled/default 2>/dev/null && log "default убран из sites-enabled" || true

# --- 3.2. Фикс odintsovlive — УБРАТЬ listen 443 ssl, поменять на :4443 ---
cat > /etc/nginx/sites-available/odintsovlive <<'NGINX'
# HTTP — redirect + certbot
server {
    listen 80;
    listen [::]:80;
    server_name odintsovlive.fvds.ru;

    location ^~ /.well-known/acme-challenge/ {
        alias /var/www/certbot/.well-known/acme-challenge/;
        default_type "text/plain";
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS через Xray fallback (:443 → :4443)
server {
    listen 4443 ssl http2;
    listen [::]:4443 ssl http2;
    server_name odintsovlive.fvds.ru;

    root /var/www/odintsovlive;
    index index.html;

    ssl_certificate /etc/letsencrypt/live/odintsovlive.fvds.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/odintsovlive.fvds.ru/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Supabase API через Kong (:8000 host network)
    location /rest/v1/ {
        proxy_pass http://localhost:8000/rest/v1/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header apikey $http_apikey;
        proxy_set_header Authorization $http_authorization;
        proxy_pass_request_headers on;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINX
log "odintsovlive: listen 443 → listen 4443 + HTTP redirect"

# --- 3.3. Фикс meridian — HTTP + proxy к docker :8080 ---
cat > /etc/nginx/sites-available/meridian <<'NGINX'
# HTTP — certbot + proxy (пока без SSL)
server {
    listen 80;
    server_name meridian.fvds.ru;

    client_max_body_size 50M;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Пока нет SSL — проксируем напрямую по HTTP
    # После получения сертификата добавим 4443 блок и redirect

    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
NGINX
log "meridian: HTTP proxy → 127.0.0.1:8080"

# --- 3.4. Фикс su10-signature — HTTP + certbot ---
cat > /etc/nginx/sites-available/su10-signature <<'NGINX'
# HTTP — certbot + статика (пока без SSL)
server {
    listen 80;
    listen [::]:80;
    server_name su10info.fvds.ru;

    location ^~ /.well-known/acme-challenge/ {
        alias /var/www/certbot/.well-known/acme-challenge/;
        default_type "text/plain";
    }

    # Пока нет SSL — отдаём статику по HTTP
    # После получения сертификата добавим 4443 блок и redirect

    root /var/www/su10-signature;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINX
log "su10-signature: HTTP + статика"

# --- 3.5. Проверить symlinks ---
ln -sf /etc/nginx/sites-available/meridian /etc/nginx/sites-enabled/meridian
ln -sf /etc/nginx/sites-available/odintsovlive /etc/nginx/sites-enabled/odintsovlive
ln -sf /etc/nginx/sites-available/su10-signature /etc/nginx/sites-enabled/su10-signature
log "Symlinks в sites-enabled обновлены"

# --- 3.6. Создать директории ---
mkdir -p /var/www/certbot/.well-known/acme-challenge
mkdir -p /var/www/odintsovlive
mkdir -p /var/www/su10-signature
log "Webroot директории созданы"

# --- 3.7. Проверить наличие SSL файлов для odintsovlive ---
if [ ! -f /etc/letsencrypt/live/odintsovlive.fvds.ru/fullchain.pem ]; then
    err "SSL сертификат odintsovlive.fvds.ru не найден!"
fi
if [ ! -f /etc/letsencrypt/options-ssl-nginx.conf ]; then
    warn "options-ssl-nginx.conf не найден — создаю стандартный"
    cat > /etc/letsencrypt/options-ssl-nginx.conf <<'SSLCONF'
ssl_session_cache shared:le_nginx_SSL:10m;
ssl_session_timeout 1440m;
ssl_session_tickets off;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_ciphers "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384";
SSLCONF
fi
if [ ! -f /etc/letsencrypt/ssl-dhparams.pem ]; then
    warn "ssl-dhparams.pem не найден — генерирую (может занять время)..."
    openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048 2>/dev/null
    log "ssl-dhparams.pem сгенерирован"
fi

# --- 3.8. Тест и запуск ---
section "Запуск System Nginx"

echo "Тестирую конфигурацию..."
if nginx -t 2>&1; then
    log "nginx -t OK"
else
    err "nginx -t FAILED! Проверь конфиги вручную."
fi

echo "Запускаю nginx..."
systemctl start nginx 2>&1
systemctl enable nginx 2>/dev/null

if systemctl is-active nginx >/dev/null 2>&1; then
    log "System Nginx запущен!"
else
    err "Nginx не запустился! Смотри: journalctl -u nginx --no-pager -n 20"
fi

# =========================================================================
section "ФАЗА 4: ФИНАЛЬНАЯ ПРОВЕРКА"
# =========================================================================

echo ""
echo -e "${BOLD}Порты:${NC}"
ss -tlnp | grep -E ':80\b|:443\b|:4443\b|:8000\b|:8080\b' || warn "Не все порты слушают"

echo ""
echo -e "${BOLD}Сервисы:${NC}"
echo -n "  nginx:  "; systemctl is-active nginx 2>/dev/null || echo "inactive"
echo -n "  xray:   "; systemctl is-active xray 2>/dev/null || echo "inactive"

echo ""
echo -e "${BOLD}Docker контейнеры:${NC}"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E 'ai-helper|NAMES'

echo ""
echo -e "${BOLD}HTTP ответы (localhost):${NC}"
for d in meridian.fvds.ru odintsovlive.fvds.ru su10info.fvds.ru; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: $d" http://127.0.0.1/ 2>/dev/null || echo "ERR")
    echo "  http://$d → $CODE"
done

echo ""
echo -e "${BOLD}HTTPS ответы через :4443 (localhost):${NC}"
for d in odintsovlive.fvds.ru; do
    CODE=$(curl -sk -o /dev/null -w "%{http_code}" -H "Host: $d" https://127.0.0.1:4443/ 2>/dev/null || echo "ERR")
    echo "  https://$d:4443 → $CODE"
done

echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  ГОТОВО!${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════${NC}"
echo ""
echo "Текущее состояние:"
echo "  ✓ Xray на :443 — не тронут"
echo "  ✓ System Nginx на :80 — запущен"
echo "  ✓ System Nginx на :4443 — odintsovlive (SSL через xray fallback)"
echo "  ✓ Docker AI Helper на 127.0.0.1:8080 — запущен"
echo "  ✓ Kong/Supabase на :8000 — не тронут"
echo ""
echo -e "${YELLOW}Следующие шаги:${NC}"
echo ""
echo "1. Получить SSL-сертификаты (замени YOUR_EMAIL):"
echo ""
echo "   certbot certonly --webroot -w /var/www/certbot \\"
echo "     -d meridian.fvds.ru --agree-tos --email YOUR_EMAIL"
echo ""
echo "   certbot certonly --webroot -w /var/www/certbot \\"
echo "     -d su10info.fvds.ru --agree-tos --email YOUR_EMAIL"
echo ""
echo "2. После получения сертификатов запусти:"
echo "   sudo bash server-add-ssl.sh"
echo ""
