"""Circuit breaker для WB API.

Если N submit-ов подряд провалились (сетевые или 5xx) — открываем breaker
на M минут. В этот период submit_order сразу возвращает failure без hit'а в WB —
не засираем WB лишними запросами и даём ему восстановиться.

После периода восстановления — half-open: следующий запрос пропускается.
Если успех → закрыто, счётчик обнулён. Если провал → опять открыто.

In-memory state (module-level) — достаточно для single-worker развёртки.
"""
from datetime import datetime, timedelta

import structlog

from app.constants import (
    CIRCUIT_BREAKER_COOLDOWN_MINUTES,
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
)

log = structlog.get_logger()

_consecutive_failures: int = 0
_opened_at: datetime | None = None


def is_open() -> bool:
    """Breaker открыт? (= не пропускаем запросы)."""
    global _consecutive_failures, _opened_at
    if _opened_at is None:
        return False
    # Период остывания прошёл → half-open (следующий запрос пойдёт)
    if datetime.now() - _opened_at >= timedelta(minutes=CIRCUIT_BREAKER_COOLDOWN_MINUTES):
        log.info("circuit_breaker_half_open")
        _opened_at = None
        _consecutive_failures = 0
        return False
    return True


def record_success() -> None:
    global _consecutive_failures, _opened_at
    if _consecutive_failures > 0 or _opened_at is not None:
        log.info("circuit_breaker_reset")
    _consecutive_failures = 0
    _opened_at = None


def record_failure() -> None:
    global _consecutive_failures, _opened_at
    _consecutive_failures += 1
    if _consecutive_failures >= CIRCUIT_BREAKER_FAILURE_THRESHOLD and _opened_at is None:
        _opened_at = datetime.now()
        log.warning(
            "circuit_breaker_opened",
            failures=_consecutive_failures,
            cooldown_minutes=CIRCUIT_BREAKER_COOLDOWN_MINUTES,
        )


def reset() -> None:
    """Для тестов и ручного сброса."""
    global _consecutive_failures, _opened_at
    _consecutive_failures = 0
    _opened_at = None
