#!/usr/bin/env bash
# =============================================================================
# server-add-ssl.sh — Добавление HTTPS блоков на :4443
# Работает с теми сертификатами, которые есть. Пропускает домены без серта.
# Запуск: sudo bash server-add-ssl.sh
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

# =========================================================================
section "Проверка сертификатов"
# =========================================================================

HAS_ODINTSOV=0; HAS_MERIDIAN=0; HAS_SU10=0

[ -f /etc/letsencrypt/live/odintsovlive.fvds.ru/fullchain.pem ] && { log "odintsovlive.fvds.ru ✓"; HAS_ODINTSOV=1; } || warn "odintsovlive.fvds.ru — нет серта"
[ -f /etc/letsencrypt/live/meridian.fvds.ru/fullchain.pem ] && { log "meridian.fvds.ru ✓"; HAS_MERIDIAN=1; } || warn "meridian.fvds.ru — нет серта"
[ -f /etc/letsencrypt/live/su10info.fvds.ru/fullchain.pem ] && { log "su10info.fvds.ru ✓"; HAS_SU10=1; } || warn "su10info.fvds.ru — нет серта (rate limit, добавишь позже)"

if [ $HAS_ODINTSOV -eq 0 ]; then
    err "Даже odintsovlive серт отсутствует — что-то не так"
fi

# Проверить ssl-dhparams и options
[ -f /etc/letsencrypt/options-ssl-nginx.conf ] || err "options-ssl-nginx.conf не найден"
[ -f /etc/letsencrypt/ssl-dhparams.pem ] || err "ssl-dhparams.pem не найден"
log "SSL конфиг-файлы на месте"

# =========================================================================
section "Бэкапы"
# =========================================================================

cp /etc/nginx/sites-available/odintsovlive "/etc/nginx/sites-available/odintsovlive.$BACKUP_SUFFIX"
cp /etc/nginx/sites-available/meridian "/etc/nginx/sites-available/meridian.$BACKUP_SUFFIX"
cp /etc/nginx/sites-available/su10-signature "/etc/nginx/sites-available/su10-signature.$BACKUP_SUFFIX"
log "Бэкапы конфигов созданы"

# =========================================================================
section "Обновление конфигов — HTTPS на :4443"
# =========================================================================

# --- odintsovlive ---
cat > /etc/nginx/sites-available/odintsovlive <<'NGINX'
# HTTP → HTTPS redirect
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
log "odintsovlive: HTTPS :4443 + HTTP redirect"

# --- meridian ---
if [ $HAS_MERIDIAN -eq 1 ]; then
cat > /etc/nginx/sites-available/meridian <<'NGINX'
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name meridian.fvds.ru;

    client_max_body_size 50M;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS через Xray fallback (:443 → :4443)
server {
    listen 4443 ssl;
    server_name meridian.fvds.ru;

    ssl_certificate /etc/letsencrypt/live/meridian.fvds.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/meridian.fvds.ru/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    client_max_body_size 50M;

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    # WebSocket
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

    # Frontend
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
NGINX
log "meridian: HTTPS :4443 + HTTP redirect"
else
    warn "meridian: пропущен (нет серта), остаётся HTTP"
fi

# --- su10-signature ---
if [ $HAS_SU10 -eq 1 ]; then
cat > /etc/nginx/sites-available/su10-signature <<'NGINX'
# HTTP → HTTPS redirect
server {
    listen 80;
    listen [::]:80;
    server_name su10info.fvds.ru;

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
    listen 4443 ssl;
    listen [::]:4443 ssl;
    server_name su10info.fvds.ru;

    ssl_certificate /etc/letsencrypt/live/su10info.fvds.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/su10info.fvds.ru/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root /var/www/su10-signature;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_types text/plain text/css text/xml text/javascript application/javascript application/json application/xml image/svg+xml;

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
NGINX
log "su10-signature: HTTPS :4443 + HTTP redirect"
else
    warn "su10-signature: пропущен (нет серта), остаётся HTTP"
    echo ""
    echo -e "${YELLOW}  Когда rate limit пройдёт, выполни:${NC}"
    echo "  certbot certonly --webroot -w /var/www/certbot -d su10info.fvds.ru --agree-tos --email YOUR_EMAIL"
    echo "  Потом перезапусти: sudo bash server-add-ssl.sh"
fi

# =========================================================================
section "Проверка и reload"
# =========================================================================

echo "Тестирую конфигурацию..."
if nginx -t 2>&1; then
    log "nginx -t OK"
else
    err "nginx -t FAILED! Бэкапы: /etc/nginx/sites-available/*.$BACKUP_SUFFIX"
fi

systemctl reload nginx
log "Nginx перезагружен"

# =========================================================================
section "ФИНАЛЬНАЯ ПРОВЕРКА"
# =========================================================================

echo ""
echo -e "${BOLD}Порты:${NC}"
ss -tlnp | grep -E ':80\b|:443\b|:4443\b|:8000\b|:8080\b'

echo ""
echo -e "${BOLD}HTTP ответы:${NC}"
for d in meridian.fvds.ru odintsovlive.fvds.ru su10info.fvds.ru; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: $d" http://127.0.0.1/ 2>/dev/null || echo "ERR")
    echo "  http://$d → $CODE"
done

echo ""
echo -e "${BOLD}HTTPS на :4443:${NC}"
for d in odintsovlive.fvds.ru meridian.fvds.ru su10info.fvds.ru; do
    if [ -f "/etc/letsencrypt/live/$d/fullchain.pem" ]; then
        CODE=$(curl -sk -o /dev/null -w "%{http_code}" --resolve "$d:4443:127.0.0.1" "https://$d:4443/" 2>/dev/null || echo "ERR")
        echo "  https://$d:4443 → $CODE"
    else
        echo "  https://$d:4443 → (нет серта, пропущен)"
    fi
done

echo ""
echo -e "${BOLD}Certbot автопродление:${NC}"
certbot renew --dry-run 2>&1 | tail -5

echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Готово!${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo ""
echo "  :443  → Xray REALITY"
echo "  :4443 → Nginx SSL (через xray fallback)"
echo "  :80   → Nginx HTTP (redirect + certbot)"
echo "  :8080 → Docker AI Helper"
echo "  :8000 → Kong/Supabase"
echo ""
if [ $HAS_SU10 -eq 0 ]; then
    echo -e "${YELLOW}  su10info.fvds.ru пока на HTTP.${NC}"
    echo -e "${YELLOW}  Rate limit пройдёт ~13:35 CET.${NC}"
    echo -e "${YELLOW}  Потом: certbot + перезапусти этот скрипт.${NC}"
fi
echo ""
