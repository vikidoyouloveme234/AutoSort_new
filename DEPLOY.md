# Деплой Auto_sort

## Требования к серверу

- Linux (Ubuntu 22.04+ или Debian 12+)
- Docker 24+ и Docker Compose v2
- Открытые порты **80** и **443** (входящий TCP)
- Домен, у которого A-запись указывает на IP сервера
- ~2 ГБ RAM, ~10 ГБ свободного места

## Шаги первого запуска

### 1. Клонировать проект

```bash
git clone https://github.com/vikidoyouloveme234/AutoSort.git /opt/auto_sort
cd /opt/auto_sort
```

### 2. Заполнить `.env`

```bash
cp .env.example .env
nano .env
```

Обязательно изменить:
- `DB_PASSWORD` — любой длинный пароль
- `FERNET_KEY` — сгенерировать: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `ADMIN_SECRET_KEY` — любая длинная случайная строка (пароль для входа в админку)
- `GOOGLE_SHEET_ID` — ID из URL гугл-таблицы
- `DOMAIN` — домен сервера (например `autosort.company.com`)
- `LETSENCRYPT_EMAIL` — email для уведомлений о просрочке сертификата
- `WB_DRY_RUN=false` — когда готовы к боевому запуску

### 3. Положить Google service account JSON

```bash
mkdir -p secrets
# Загрузите файл сервисного аккаунта сюда:
# secrets/google_sa.json
```

Дать сервисному аккаунту доступ **Редактор** к Google-таблице.

### 4. Собрать образ app

```bash
docker compose build app
```

### 5. Выпустить TLS-сертификат (первый раз)

```bash
chmod +x scripts/init-letsencrypt.sh
./scripts/init-letsencrypt.sh
```

Для тестов сначала можно запустить в staging-режиме:
```bash
./scripts/init-letsencrypt.sh staging
```
(выдаст недоверенный тестовый сертификат, не расходует rate limit Let's Encrypt)

### 6. Запустить весь стек

```bash
docker compose up -d
```

Проверить:
```bash
docker compose ps                  # все сервисы healthy
curl https://$DOMAIN/healthz       # → {"status": "ok"}
```

### 7. Засеять склады в БД

```bash
docker compose exec app python -m scripts.seed_warehouses
```

### 8. Зайти в админку

Открыть `https://<DOMAIN>` → ввести `ADMIN_SECRET_KEY` из `.env` → вставить куки WB через форму в «Настройки».

### 9. Запустить smoke-test

Проверяет что все компоненты живые. **Обязательно** перед передачей менеджеру:

```bash
docker compose exec app py -m scripts.smoke_test
```

Проверяет: БД, миграции, склады, куки, app_state, Google Sheets. Все 6 проверок должны быть `OK`. Если что-то `FAIL` — исправить до начала работы.

## Админ-панель — что доступно

- **Дашборд**: состояние бота (🟢 Работает / ⏸ Остановлен / 🔴 Ошибка), время последней обработки, 7 метрик статистики, индикатор сессии WB
- **Кнопка «⏸ Остановить»** — пауза автоматических задач (ручной запуск работает)
- **Смена интервала опроса** (Настройки → поле «Интервал опроса таблицы», 1-60 мин) — применяется на лету без перезапуска
- **Кнопка «✕» рядом с ошибкой** — очистить информацию о last_error (после исправления причины)
- **«Сбросить все сессии»** (Настройки → блок «Безопасность») — при утечке куки / увольнении сотрудника. Все залогиненные получат login screen при следующем клике.

## Безопасность — встроенные защиты

- **CSRF** на всех POST-эндпоинтах (double-submit cookie pattern)
- **Rate limiting**: 5 попыток/мин на `/login` (защита от bruteforce), 10/мин на admin-actions (защита от клик-спама)
- **Secure cookie** флаг при HTTPS (через `SESSION_COOKIE_SECURE=true`)
- **Session revocation** через `session_version` в БД — revoke всех cookies одной кнопкой
- **Circuit breaker** на submit к WB: 10 подряд фейлов → пауза 30 мин (не засираем WB при его outage)
- **Retry с exponential backoff** — 3 попытки (1s → 2s → 4s) на сетевых ошибках
- **Логи автоматически ротируются** — Docker ограничивает 50MB × 3 файла на контейнер

## Внешний мониторинг (рекомендуется)

### Uptime

Бесплатный внешний чек — чтобы узнать, что бот упал, ещё до жалобы менеджера:

1. Зарегистрируйся на [uptimerobot.com](https://uptimerobot.com) (free: 50 мониторов, 5-мин интервал)
2. Добавить **HTTPS monitor** на `https://<DOMAIN>/healthz`
3. Ожидаемый ответ: `{"status":"ok"}`, статус 200
4. Алерты на email / Telegram / Discord

## Обслуживание

### Обновление кода

```bash
cd /opt/auto_sort
git pull
docker compose build app
docker compose up -d app
```

(миграции alembic применяются автоматически при старте контейнера)

### Логи

```bash
docker compose logs -f app         # логи бота
docker compose logs -f nginx       # доступ / ошибки nginx
docker compose logs certbot        # обновление сертификатов
```

### Бэкап БД

**Автоматически**: контейнер `backup` в docker-compose делает `pg_dump` раз в сутки в volume `backups`, хранит 14 последних (ротация). Ничего делать не надо.

Посмотреть бэкапы:
```bash
docker compose exec backup ls -lh /backups/
```

Восстановить из бэкапа:
```bash
docker compose exec backup sh -c 'gunzip -c /backups/backup_20260418_030000.sql.gz | \
  PGPASSWORD=$POSTGRES_PASSWORD psql -h db -U $POSTGRES_USER $POSTGRES_DB'
```

**Ручной бэкап** (например, перед обновлением):
```bash
docker compose exec db pg_dump -U $DB_USER $DB_NAME > backup_$(date +%F).sql
```

### Ротация сертификата

Certbot-контейнер сам обновляет сертификаты каждые 12 часов (за 30 дней до истечения). Ничего делать не надо.

Если надо форсировать обновление:
```bash
docker compose run --rm --entrypoint certbot certbot renew --force-renewal --webroot -w /var/www/certbot
docker compose exec nginx nginx -s reload
```

## Чек-лист безопасности

- [ ] `ADMIN_SECRET_KEY` длиной минимум 32 символа
- [ ] `DB_PASSWORD` изменён со значения по умолчанию
- [ ] `FERNET_KEY` **сохранён в надёжное место** (без него расшифровать куки в БД невозможно — менеджеру придётся вводить заново)
- [ ] Firewall закрывает все порты кроме 80, 443, 22 (SSH)
- [ ] Бэкап БД настроен (раз в сутки минимум)
- [ ] Мониторинг на `https://$DOMAIN/healthz` (UptimeRobot / Pingdom)

## Что делать если что-то сломалось

**Сайт не открывается:**
- `docker compose ps` — все контейнеры должны быть `Up`, healthcheck OK
- `docker compose logs nginx` — проверить, что nginx стартанул без ошибок
- Если `ssl_certificate` ошибка — сертификат не выдан, повторить `./scripts/init-letsencrypt.sh`

**Бот не обрабатывает задания:**
- Открыть админку → проверить индикатор сессии WB (🟢/🔴)
- Если 🔴 — обновить куки через форму
- `docker compose logs app` — смотреть подробности

**Сессия WB «Подтверждено: 3 дн назад»:**
- Нажать «Проверить сессию» — если подтвердится, всё ок
- Если ошибка — нужно обновить куки вручную

**Admin-панель выдаёт 502:**
- `docker compose restart app`
- Если не помогло — `docker compose logs app` и написать разработчику
