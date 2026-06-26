#!/bin/bash

# ====================================================
# Скрипт первичного получения SSL-сертификата Let's Encrypt
# Запустить ОДИН РАЗ на сервере перед docker compose up
# ====================================================

DOMAIN="${DOMAIN:-app.example.com}"   # <-- УКАЖИ СВОЙ ДОМЕН (или передай через env)
EMAIL="${EMAIL:-your-email@example.com}"   # <-- УКАЖИ СВОЙ EMAIL
DATA_PATH=./certbot
RSA_KEY_SIZE=4096
STAGING=0  # Поставь 1 для тестирования (без лимитов Let's Encrypt)

if [ "$STAGING" != "0" ]; then
  STAGING_ARG="--staging"
else
  STAGING_ARG=""
fi

echo "### Создание директорий..."
mkdir -p "$DATA_PATH/conf/live/$DOMAIN"
mkdir -p "$DATA_PATH/www"

echo "### Создание временного самоподписанного сертификата..."
docker compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:$RSA_KEY_SIZE -days 1 \
    -keyout '/etc/letsencrypt/live/$DOMAIN/privkey.pem' \
    -out '/etc/letsencrypt/live/$DOMAIN/fullchain.pem' \
    -subj '/CN=localhost'" certbot

echo "### Запуск nginx..."
docker compose up --force-recreate -d nginx

echo "### Удаление временного сертификата..."
docker compose run --rm --entrypoint "\
  rm -rf /etc/letsencrypt/live/$DOMAIN && \
  rm -rf /etc/letsencrypt/archive/$DOMAIN && \
  rm -rf /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

echo "### Получение сертификата Let's Encrypt..."
docker compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $STAGING_ARG \
    --email $EMAIL \
    --agree-tos \
    --no-eff-email \
    -d $DOMAIN \
    --rsa-key-size $RSA_KEY_SIZE \
    --force-renewal" certbot

echo "### Перезагрузка nginx..."
docker compose exec nginx nginx -s reload

echo "### Готово! Сертификат получен для $DOMAIN"
