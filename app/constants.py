"""Централизованные константы приложения.

Собраны здесь чтобы:
- не искать их по 5 разным файлам
- менять значения в одном месте
- были видны все «тюнинг-ручки» проекта
"""

# --- WB API rate limit ---
WB_RATE_LIMIT_RPS = 4           # эмпирически > 4.5 → 429
WB_RATE_LIMIT_PERIOD_SEC = 1

# --- Retry policy ---
RETRY_MAX_ATTEMPTS = 3          # по ТЗ
RETRY_INITIAL_DELAY_SEC = 1.0   # backoff 1→2→4s

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
