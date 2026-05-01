"""Rate limiters + retry для Google Sheets API.

**Два раздельных пула** (per-user официальные лимиты Google):
- `acquire_read()` — 60 read/min
- `acquire_write()` — 60 write/min
Суммарно 120 операций/мин на наш service account.

**Retry на 429** через `with_retry()`: 4 попытки с exponential backoff
(1→2→4→8s) + jitter ±20%. На 429 уважаем `Retry-After` если сервер прислал
(gspread кладёт его в `e.response.headers`).

Sliding window лимитер sync (т.к. gspread sync). При насыщении вызывает
`time.sleep` — блокирует event loop. Для текущей последовательной обработки
это ок (одна задача за раз). Если в будущем параллелим — оборачиваем
gspread в `asyncio.to_thread`.
"""
import random
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TypeVar

import structlog
from gspread.exceptions import APIError

from app.constants import (
    SHEETS_MAX_ATTEMPTS,
    SHEETS_READ_LIMIT_PER_MIN,
    SHEETS_RETRY_INITIAL_DELAY_SEC,
    SHEETS_WRITE_LIMIT_PER_MIN,
)

log = structlog.get_logger()

T = TypeVar("T")


class SheetsRateLimiter:
    def __init__(self, max_calls: int, period_sec: int = 60, *, name: str = "sheets") -> None:
        self._max_calls = max_calls
        self._period = period_sec
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()
        self._name = name

    def acquire(self) -> None:
        """Блокирует пока не освободится slot. Лок держим до возврата
        (намеренно: FIFO, без stampede)."""
        with self._lock:
            while True:
                now = time.monotonic()
                while self._calls and self._calls[0] <= now - self._period:
                    self._calls.popleft()

                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return

                sleep_for = self._calls[0] + self._period - now
                if sleep_for <= 0:
                    continue
                log.warning(
                    "sheets_rate_limit_throttled",
                    pool=self._name, sleep_sec=round(sleep_for, 2),
                    active=len(self._calls), limit=self._max_calls,
                )
                time.sleep(sleep_for)


_read_limiter = SheetsRateLimiter(SHEETS_READ_LIMIT_PER_MIN, name="read")
_write_limiter = SheetsRateLimiter(SHEETS_WRITE_LIMIT_PER_MIN, name="write")


def acquire_read() -> None:
    _read_limiter.acquire()


def acquire_write() -> None:
    _write_limiter.acquire()


def reset() -> None:
    """Сброс обоих пулов — для тестов."""
    _read_limiter._calls.clear()
    _write_limiter._calls.clear()


# --- Retry ---


def _parse_retry_after(e: APIError) -> float | None:
    """Sheets-429 может содержать Retry-After в response headers."""
    try:
        headers = e.response.headers  # type: ignore[attr-defined]
    except AttributeError:
        return None
    raw = headers.get("Retry-After") if headers else None
    if not raw:
        return None
    try:
        sec = float(raw)
    except (TypeError, ValueError):
        return None
    return sec if 0 < sec <= 60 else None


def with_retry(label: str, op: Callable[[], T]) -> T:
    """Запускает sync gspread-операцию с retry на 429 / транзиент.

    Не ретраит:
    - 4xx кроме 429 (семантический ответ — ошибка в коде/данных)
    - 401/403 (auth-проблема, retry не поможет)

    Retries:
    - 429 — exponential backoff с jitter, или Retry-After если сервер прислал
    - 5xx — exponential backoff
    """
    delay = SHEETS_RETRY_INITIAL_DELAY_SEC
    last_exc: Exception | None = None

    for attempt in range(1, SHEETS_MAX_ATTEMPTS + 1):
        try:
            return op()
        except APIError as e:
            code = getattr(e, "code", None)
            if code is None:
                response = getattr(e, "response", None)
                if response is not None:
                    code = getattr(response, "status_code", None)
            last_exc = e

            # 401/403 не ретраим — auth не починится сама
            if code in (401, 403):
                log.error("sheets_auth_error", label=label, code=code)
                raise

            # 429 — sleep по подсказке сервера или backoff
            if code == 429:
                if attempt >= SHEETS_MAX_ATTEMPTS:
                    log.error("sheets_429_exhausted", label=label, attempts=attempt)
                    raise
                hint = _parse_retry_after(e)
                sleep_for = hint if hint is not None else delay
                sleep_for *= random.uniform(0.8, 1.2)  # jitter
                log.warning("sheets_429_retry", label=label, attempt=attempt,
                            sleep_sec=round(sleep_for, 2), server_hint=hint is not None)
                time.sleep(sleep_for)
                if hint is None:
                    delay *= 2
                continue

            # 5xx — backoff и retry
            if code is not None and code >= 500:
                if attempt >= SHEETS_MAX_ATTEMPTS:
                    log.error("sheets_5xx_exhausted", label=label, code=code, attempts=attempt)
                    raise
                sleep_for = delay * random.uniform(0.8, 1.2)
                log.warning("sheets_5xx_retry", label=label, code=code,
                            attempt=attempt, sleep_sec=round(sleep_for, 2))
                time.sleep(sleep_for)
                delay *= 2
                continue

            # 4xx (кроме 429) — семантическая ошибка, не ретраим
            log.error("sheets_4xx_error", label=label, code=code)
            raise

    assert last_exc is not None
    raise last_exc
