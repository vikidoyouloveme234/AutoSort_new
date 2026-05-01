"""Rate limiter для Google Sheets API.

Sync (т.к. gspread синхронный). Sliding window — отслеживает все запросы
за последние 60 секунд, блокирует если превышен лимит. Thread-safe через
threading.Lock — на случай если Sheets-вызовы будут идти из разных тредов
(сейчас не идут, но дёшево добавить).

Лимит — `SHEETS_RATE_LIMIT_PER_MIN` (60 по умолчанию). Официально Google
даёт 60 read + 60 write на пользователя в минуту, но мы делим один бюджет —
проще и безопаснее.

NB: блокирует event loop (т.к. sync sleep). Для текущей архитектуры это ок:
бот обрабатывает задачи последовательно, нечему параллельно ждать.
"""
import threading
import time
from collections import deque

import structlog

from app.constants import SHEETS_RATE_LIMIT_PER_MIN

log = structlog.get_logger()


class SheetsRateLimiter:
    def __init__(self, max_calls: int, period_sec: int = 60) -> None:
        self._max_calls = max_calls
        self._period = period_sec
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Блокирует пока не освободится slot. Записывает время вызова в окно.

        Lock держим до возврата (включая sleep). Другие caller'ы ждут на
        локe — это намеренно: ровно один тред за раз продвигается, очередь
        на конкуренции — простая, без stampede.
        """
        with self._lock:
            while True:
                now = time.monotonic()
                # Чистим устаревшие отметки
                while self._calls and self._calls[0] <= now - self._period:
                    self._calls.popleft()

                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return

                # Лимит достигнут — спим до того момента, как самая старая
                # отметка вылетит из окна.
                sleep_for = self._calls[0] + self._period - now
                if sleep_for <= 0:
                    # Окно уже сдвинулось (race) — повторим цикл, очистится.
                    continue
                log.warning(
                    "sheets_rate_limit_throttled",
                    sleep_sec=round(sleep_for, 2),
                    active_calls=len(self._calls),
                    limit=self._max_calls,
                )
                time.sleep(sleep_for)


_limiter = SheetsRateLimiter(SHEETS_RATE_LIMIT_PER_MIN)


def acquire() -> None:
    """Глобальная точка входа: вызвать перед каждым обращением к Sheets API."""
    _limiter.acquire()


def reset() -> None:
    """Сброс — для тестов."""
    _limiter._calls.clear()
