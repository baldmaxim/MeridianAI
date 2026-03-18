# Сервер — архитектура и управление

**Сервер:** Ubuntu 24.04, IP: 80.74.28.233
**Дата настройки:** 2026-03-16

---

## Финальная архитектура

```
Internet :443 → Xray (VLESS REALITY)
                  ├── VPN-клиенты → обработка xray
                  └── fallback → :4443 (System Nginx SSL)

System Nginx :4443 (SSL termination через xray fallback):
  ├── odintsovlive.fvds.ru → SPA /var/www/odintsovlive + Supabase API → :8000
  ├── meridian.fvds.ru     → proxy → 127.0.0.1:8080 (AI Helper Docker)
  └── su10info.fvds.ru     → SPA /var/www/su10-signature

System Nginx :80 (HTTP):
  ├── /.well-known/acme-challenge/ → certbot webroot
  └── всё остальное → 301 → HTTPS

127.0.0.1:8080 → Docker AI Helper:
  docker-nginx → frontend:80 + backend:8000 (внутренняя сеть)

0.0.0.0:8000 → Kong/OpenResty (Supabase, host network)
```

---

## Порты

| Порт | Процесс | Назначение |
|------|---------|-----------|
| :80 | system nginx | HTTP redirect + certbot |
| :443 | xray | VLESS REALITY VPN |
| :4443 | system nginx | HTTPS (через xray fallback) |
| 127.0.0.1:8080 | docker nginx (ai-helper) | AI Helper reverse proxy |
| :8000 | kong/openresty (supabase) | Supabase API gateway |

---

## Домены

| Домен | HTTP :80 | HTTPS :4443 | Backend |
|-------|----------|-------------|---------|
| meridian.fvds.ru | 301 → HTTPS | proxy → 127.0.0.1:8080 | AI Helper Docker |
| odintsovlive.fvds.ru | 301 → HTTPS | SPA + /rest/v1/ → :8000 | Supabase |
| su10info.fvds.ru | 301 → HTTPS | SPA статика | нет |

---

## Файлы конфигурации

### System Nginx (на сервере)
- `/etc/nginx/nginx.conf` — главный конфиг (стандартный)
- `/etc/nginx/sites-available/odintsovlive` → listen :80 + :4443 ssl
- `/etc/nginx/sites-available/meridian` → listen :80 + :4443 ssl
- `/etc/nginx/sites-available/su10-signature` → listen :80 + :4443 ssl
- `/etc/nginx/sites-enabled/` — symlinks на sites-available

### Docker AI Helper
- `/opt/ai-helper/docker-compose.yml` — postgres, backend, frontend, nginx
- `/opt/ai-helper/nginx/nginx.conf` — HTTP-only proxy (без SSL)
- `/opt/ai-helper/.env` — API ключи

### Xray
- `/usr/local/etc/xray/config.json` — VLESS REALITY, fallback dest: 4443
- `/etc/systemd/system/xray.service`

### Supabase
- `/opt/supabase/docker-compose.yml`
- Kong работает в host network на :8000

### SSL-сертификаты
- `/etc/letsencrypt/live/odintsovlive.fvds.ru/` — до 30.05.2026
- `/etc/letsencrypt/live/meridian.fvds.ru/` — до 14.06.2026
- `/etc/letsencrypt/live/su10info.fvds.ru/` — (получить после rate limit)

---

## Управление

### Перезапуск nginx
```bash
nginx -t && systemctl reload nginx
```

### Перезапуск AI Helper
```bash
cd /opt/ai-helper
docker compose restart
# или полная пересборка:
docker compose down && docker compose up -d --build
```

### Статус всех сервисов
```bash
systemctl status nginx xray
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
ss -tlnp | grep -E ':80\b|:443\b|:4443\b|:8000\b|:8080\b'
```

### Продление сертификатов
```bash
certbot renew              # автоматически по cron
certbot renew --dry-run    # тест
certbot certificates       # список
```

---

## Добавление su10info SSL (после rate limit)

```bash
certbot certonly --webroot -w /var/www/certbot \
  -d su10info.fvds.ru --agree-tos --email YOUR_EMAIL

sudo bash /root/server-add-ssl.sh
```

---

## Скрипты (в проекте и на сервере /root/)

| Скрипт | Назначение |
|--------|-----------|
| `server-diagnose.sh` | Readonly диагностика всей архитектуры |
| `server-fix.sh` | Фикс docker-compose + system nginx (одноразовый) |
| `server-add-ssl.sh` | Добавление HTTPS блоков на :4443 (идемпотентный) |

---

## Что было исправлено (2026-03-16)

### Проблема
System nginx падал при старте: `bind() to 0.0.0.0:443 failed (Address already in use)`.
Порт 80 никто не слушал. Сайты не работали.

### Корневые причины
1. **odintsovlive конфиг** содержал `listen 443 ssl` → конфликт с xray на :443
2. **docker-compose.yml** AI Helper публиковал порты `80:80` и `443:443` → конфликт с xray и system nginx
3. Docker nginx контейнер не мог запуститься (status: Created)

### Исправления
1. docker-compose.yml: nginx порты → `127.0.0.1:8080:80`, удалён certbot сервис
2. Docker nginx.conf: убран SSL-блок, оставлен HTTP-only proxy
3. odintsovlive: `listen 443` → `listen 4443` (через xray fallback)
4. meridian и su10-signature: добавлены HTTPS-блоки на :4443
5. SSL-сертификаты через system certbot (webroot на :80)

---

## Что НЕ трогать

- **Xray** `/usr/local/etc/xray/config.json` — VPN, не менять без понимания
- **Supabase** `/opt/supabase/` — Kong на host network :8000
- **Порт 443** — принадлежит xray, nginx НЕ должен на нём слушать
