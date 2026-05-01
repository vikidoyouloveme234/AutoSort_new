"""Централизованные константы приложения.

Собраны здесь чтобы:
- не искать их по 5 разным файлам
- менять значения в одном месте
- были видны все «тюнинг-ручки» проекта
"""

# --- WB API rate limit ---
# Probe-замер 2026-04-28 на /stocks (scripts/probe_wb_rate_limit.py):
#   1 req/s → 0% 429
#   2 req/s → 10% 429
#   3 req/s → 60% 429
# Реальный потолок ниже, чем считалось раньше («> 4.5 → 429» оказалось мифом).
# Ставим 2 — допустимый компромисс: редкие 429 ловит retry-логика в _retry.py
# (с jitter и Retry-After). На 1 — было бы безопаснее, но 100 заданий тогда
# обрабатываются ~7 мин против ~3.5 мин на 2 req/s.
WB_RATE_LIMIT_RPS = 2
WB_RATE_LIMIT_PERIOD_SEC = 1

# --- Retry policy ---
RETRY_MAX_ATTEMPTS = 3          # по ТЗ — для сетевых ошибок (1→2→4s)
RETRY_INITIAL_DELAY_SEC = 1.0
RATE_LIMIT_MAX_ATTEMPTS = 4     # для 429 — 4 попытки, backoff 2→4→8→16s (~30s)
RATE_LIMIT_RETRY_INITIAL_DELAY_SEC = 2.0
RATE_LIMIT_RETRY_AFTER_CAP_SEC = 30.0  # если сервер просит ждать дольше — отступаем

# --- wb-seller-lk кэш ---
SELLER_LK_CACHE_TTL_SEC = 240   # токен живёт 5 мин, кэш на 4

# --- Delivery watcher ---
WATCH_WINDOW_DAYS = 7           # после этого срока не трекаем
PARTIAL_THRESHOLD = 0.9         # ≥90% = DONE_PARTIAL, 100% = DONE_BOT

# --- Interval ---
DEFAULT_POLL_INTERVAL_MINUTES = 5
POLL_INTERVAL_MIN = 1
POLL_INTERVAL_MAX = 60

# --- Stocks endpoint ---
STOCKS_MAX_NM_IDS_PER_REQUEST = 1000   # лимит WB API

# --- Google Sheets API rate limit ---
# Официальный лимит per-user: 60 read/min + 60 write/min РАЗДЕЛЬНО (это два
# независимых пула — https://developers.google.com/sheets/api/limits). Держим
# два лимитера по 60/min — суммарно 120 операций/мин на сервисный аккаунт.
SHEETS_READ_LIMIT_PER_MIN = 60
SHEETS_WRITE_LIMIT_PER_MIN = 60

# --- Sheets retry ---
SHEETS_MAX_ATTEMPTS = 4
SHEETS_RETRY_INITIAL_DELAY_SEC = 1.0   # 1→2→4→8s

# --- Sheets batching ---
# Сколько строк аккумулируем в буфере writer'а перед flush'ем. На batch
# больше = меньше API-вызовов и лучше throughput, но дольше ждать пока
# маркер «В очереди бота» появится в таблице. 10 — компромисс: при
# 1-2 task/sec задержка маркера ~5-10 сек, незаметно для менеджера.
SHEETS_WRITE_BATCH_ROWS = 10

# --- Stats cache (dashboard) ---
STATS_CACHE_TTL_SEC = 300       # 5 минут

# --- Admin session ---
SESSION_COOKIE_MAX_AGE_SEC = 7 * 24 * 3600    # 7 дней
CSRF_COOKIE_MAX_AGE_SEC = 7 * 24 * 3600

# --- Admin panel rate limiting ---
# Login — чтобы не бруфорсить пароль
LOGIN_RATE_LIMIT_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SEC = 60
# Action endpoints — от клик-спама
ACTION_RATE_LIMIT_ATTEMPTS = 10
ACTION_RATE_LIMIT_WINDOW_SEC = 60

# --- Dead letter escalation ---
DEAD_LETTER_AGE_DAYS = 3        # needs_attention старше этого попадает в escalation log

# --- Circuit breaker ---
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 10    # подряд неудач
CIRCUIT_BREAKER_COOLDOWN_MINUTES = 30     # пауза после тripa

# --- Delivery watcher ---
DELIVERY_RUN_HOUR_MSK = 7       # раз в сутки

# --- Daily cookie check ---
COOKIE_CHECK_HOUR_MSK = 8

# --- Slot rush windows (МСК) ---
SLOT_RUSH_HOURS_MSK = "0,9,18"
