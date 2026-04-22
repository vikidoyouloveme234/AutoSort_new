#!/bin/bash
# Первичная выдача Let's Encrypt сертификата.
# Запускать ОДИН РАЗ после заполнения .env перед первым `docker compose up -d`.
#
# Использует паттерн "nginx-certbot" (wmnnd/nginx-certbot):
#   1. Генерит dummy self-signed сертификат чтобы nginx смог стартовать
#   2. Запускает nginx
#   3. Дёргает certbot через webroot — получает настоящий cert
#   4. Релоадит nginx с реальным cert

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "Ошибка: нет файла .env. Скопируйте .env.example → .env и заполните."
    exit 1
fi

# Подтягиваем DOMAIN и LETSENCRYPT_EMAIL из .env
set -a; source .env; set +a

if [[ -z "${DOMAIN:-}" || -z "${LETSENCRYPT_EMAIL:-}" ]]; then
    echo "Ошибка: в .env должны быть заданы DOMAIN и LETSENCRYPT_EMAIL."
    exit 1
fi

STAGING="${1:-}"  # передай "staging" первым аргументом для тестов Let's Encrypt
STAGING_FLAG=""
if [[ "$STAGING" == "staging" ]]; then
    STAGING_FLAG="--staging"
    echo ">>> STAGING MODE: выпустится тестовый сертификат (не доверяется браузером)"
fi

echo ">>> Создаём dummy-сертификат для $DOMAIN"
docker compose run --rm --entrypoint sh certbot -c "\
  mkdir -p /etc/letsencrypt/live/$DOMAIN && \
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem \
    -out  /etc/letsencrypt/live/$DOMAIN/fullchain.pem \
    -subj '/CN=localhost'"

echo ">>> Поднимаем nginx с dummy-сертификатом"
docker compose up -d nginx

echo ">>> Удаляем dummy-сертификат"
docker compose run --rm --entrypoint sh certbot -c "\
  rm -rf /etc/letsencrypt/live/$DOMAIN && \
  rm -rf /etc/letsencrypt/archive/$DOMAIN && \
  rm -f  /etc/letsencrypt/renewal/$DOMAIN.conf"

echo ">>> Запрашиваем реальный сертификат у Let's Encrypt"
docker compose run --rm --entrypoint certbot certbot certonly \
    --webroot -w /var/www/certbot \
    $STAGING_FLAG \
    --email "$LETSENCRYPT_EMAIL" \
    -d "$DOMAIN" \
    --rsa-key-size 2048 \
    --agree-tos \
    --no-eff-email \
    --force-renewal

echo ">>> Перезагружаем nginx с реальным сертификатом"
docker compose exec nginx nginx -s reload

echo ">>> Готово. Откройте https://$DOMAIN"
