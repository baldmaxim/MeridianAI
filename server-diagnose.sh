#!/usr/bin/env bash
# =============================================================================
# server-diagnose.sh — Полная диагностика веб-архитектуры сервера
# Запуск: sudo bash server-diagnose.sh
# Ничего не меняет, только читает и выводит информацию.
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

section() { echo -e "\n${CYAN}${BOLD}═══════════════════════════════════════════════════════════${NC}"; echo -e "${CYAN}${BOLD}  $1${NC}"; echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════${NC}"; }
subsec()  { echo -e "\n${YELLOW}--- $1 ---${NC}"; }

[[ $EUID -ne 0 ]] && { echo -e "${RED}Запускай от root: sudo bash $0${NC}"; exit 1; }

section "1. ПОРТЫ: кто слушает 80, 443, 4443, 8000, 8080"
ss -tlnp | head -1
ss -tlnp | grep -E ':80\b|:443\b|:4443\b|:8000\b|:8080\b' || echo "(ничего не найдено)"

section "2. ВСЕ NGINX-ПРОЦЕССЫ"
ps aux | grep -E '[n]ginx' || echo "(nginx процессов нет)"

subsec "2.1. PID процесса на :80 и его cgroup (контейнер или хост?)"
PORT80_PID=$(ss -tlnp | grep ':80 ' | head -1 | grep -oP 'pid=\K[0-9]+' || true)
if [ -n "$PORT80_PID" ]; then
    echo "PID на :80: $PORT80_PID"
    echo "Cmdline: $(cat /proc/$PORT80_PID/cmdline 2>/dev/null | tr '\0' ' ' || echo 'N/A')"
    echo "Cgroup:"
    cat /proc/$PORT80_PID/cgroup 2>/dev/null || echo "N/A"
else
    echo "(порт 80 никто не слушает)"
fi

section "3. SYSTEMD СЕРВИСЫ"
subsec "3.1. nginx.service"
systemctl status nginx --no-pager 2>&1 | head -15 || true

subsec "3.2. xray.service"
systemctl status xray --no-pager 2>&1 | head -10 || true

subsec "3.3. Логи nginx (последние 30 строк)"
journalctl -u nginx --no-pager -n 30 2>/dev/null || echo "(логов нет)"

section "4. SYSTEM NGINX КОНФИГУРАЦИЯ"
subsec "4.1. nginx -T (тест конфигурации)"
nginx -T 2>&1 | head -80 || echo "(nginx -T не удалось)"

subsec "4.2. sites-enabled"
ls -la /etc/nginx/sites-enabled/ 2>/dev/null || echo "(директории нет)"

subsec "4.3. sites-available"
ls -la /etc/nginx/sites-available/ 2>/dev/null || echo "(директории нет)"

subsec "4.4. Содержимое sites-enabled/*"
for f in /etc/nginx/sites-enabled/*; do
    [ -e "$f" ] || continue
    echo -e "\n${GREEN}=== $f ===${NC}"
    if [ -L "$f" ]; then
        echo "(symlink → $(readlink -f "$f"))"
    else
        echo "(ОБЫЧНЫЙ ФАЙЛ, не symlink!)"
    fi
    cat "$f" 2>/dev/null
done

subsec "4.5. Содержимое sites-available/*"
for f in /etc/nginx/sites-available/*; do
    [ -e "$f" ] || continue
    echo -e "\n${GREEN}=== $f ===${NC}"
    cat "$f" 2>/dev/null
done

section "5. XRAY КОНФИГУРАЦИЯ"
subsec "5.1. Systemd unit"
systemctl cat xray 2>/dev/null | head -20 || echo "(unit не найден)"

subsec "5.2. Поиск конфиг-файла xray"
for p in /usr/local/etc/xray/config.json /etc/xray/config.json /usr/local/etc/xray/*.json /etc/xray/*.json; do
    [ -f "$p" ] && echo "Найден: $p"
done

subsec "5.3. Xray inbounds + fallbacks (без ключей)"
# Выводим только inbounds секцию, маскируя приватные данные
for p in /usr/local/etc/xray/config.json /etc/xray/config.json; do
    if [ -f "$p" ]; then
        echo -e "${GREEN}Файл: $p${NC}"
        python3 -c "
import json, sys
with open('$p') as f:
    cfg = json.load(f)
# Показать только inbounds (маскируя id/password/privateKey)
inbounds = cfg.get('inbounds', [])
for ib in inbounds:
    # Маскируем чувствительные поля
    if 'settings' in ib:
        s = ib['settings']
        if 'clients' in s:
            for c in s['clients']:
                for k in ('id', 'password', 'email'):
                    if k in c:
                        c[k] = '***MASKED***'
    if 'streamSettings' in ib:
        ss = ib['streamSettings']
        if 'realitySettings' in ss:
            rs = ss['realitySettings']
            for k in ('privateKey', 'shortIds'):
                if k in rs:
                    rs[k] = '***MASKED***'
    # Показать inbound
    print(json.dumps(ib, indent=2, ensure_ascii=False))
" 2>/dev/null || echo "(не удалось распарсить JSON)"
        break
    fi
done

section "6. DOCKER"
subsec "6.1. Все контейнеры (включая stopped)"
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "(docker недоступен)"

subsec "6.2. Docker networks"
docker network ls 2>/dev/null || true

subsec "6.3. Поиск docker-compose файлов meridian"
find / -maxdepth 5 -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'compose.yml' -o -name 'compose.yaml' 2>/dev/null | grep -i -E 'meridian' || echo "(не найдено по meridian/meridian)"
echo "Все найденные compose файлы:"
find / -maxdepth 4 -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'compose.yml' 2>/dev/null || true

subsec "6.4. Docker-compose.yml meridian (содержимое)"
for d in $(find / -maxdepth 5 -name 'docker-compose.yml' 2>/dev/null | grep -i -E 'meridian' | head -3); do
    echo -e "${GREEN}=== $d ===${NC}"
    cat "$d"
done

subsec "6.5. Docker nginx конфиг (если есть)"
# Ищем nginx.conf рядом с docker-compose
for d in $(find / -maxdepth 5 -name 'docker-compose.yml' 2>/dev/null | grep -i -E 'meridian' | head -3); do
    DIR=$(dirname "$d")
    if [ -f "$DIR/nginx/nginx.conf" ]; then
        echo -e "${GREEN}=== $DIR/nginx/nginx.conf ===${NC}"
        cat "$DIR/nginx/nginx.conf"
    fi
done

subsec "6.6. supabase-kong inspect (порты и сети)"
docker inspect supabase-kong --format '{{json .NetworkSettings.Ports}}' 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "(kong не найден или нет python3)"
docker inspect supabase-kong --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || true

section "7. IPTABLES / NFT"
subsec "7.1. NAT таблица"
iptables -t nat -L -n 2>/dev/null | head -40 || echo "(iptables недоступен)"

subsec "7.2. UFW статус"
ufw status 2>/dev/null || echo "(ufw недоступен)"

section "8. СЕРТИФИКАТЫ"
subsec "8.1. Certbot certificates"
certbot certificates 2>/dev/null || echo "(certbot не установлен)"

subsec "8.2. /etc/letsencrypt/live/"
ls -la /etc/letsencrypt/live/ 2>/dev/null || echo "(директории нет)"

section "9. HTTP-ОТВЕТЫ (локально)"
subsec "9.1. curl localhost:80 с разными Host"
for d in meridian.fvds.ru odintsovlive.fvds.ru su10info.fvds.ru; do
    echo -e "\n${GREEN}Host: $d${NC}"
    curl -s -o /dev/null -w "HTTP %{http_code}, redirect: %{redirect_url}\n" -H "Host: $d" http://127.0.0.1/ 2>/dev/null || echo "FAILED"
done

subsec "9.2. curl localhost:4443 (если слушает)"
if ss -tlnp | grep -q ':4443'; then
    for d in meridian.fvds.ru odintsovlive.fvds.ru su10info.fvds.ru; do
        echo -e "\n${GREEN}Host: $d${NC}"
        curl -sk -o /dev/null -w "HTTP %{http_code}\n" -H "Host: $d" https://127.0.0.1:4443/ 2>/dev/null || echo "FAILED"
    done
else
    echo "(порт 4443 не слушает)"
fi

subsec "9.3. curl localhost:8080 (если слушает)"
if ss -tlnp | grep -q ':8080'; then
    curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8080/ 2>/dev/null || echo "FAILED"
else
    echo "(порт 8080 не слушает)"
fi

section "10. РЕЗЮМЕ"
echo ""
echo "Диагностика завершена. Скопируй ВЕСЬ вывод и пришли в чат."
echo ""
