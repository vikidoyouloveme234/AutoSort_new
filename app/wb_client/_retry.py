"""Retry-обёртка для сетевых вызовов.

По ТЗ: для неустойчивых операций (сеть, WB API) — 3 попытки с
экспоненциальной задержкой. Retries только на сетевых ошибках;
4xx/5xx HTTP — не retry (это семантические ответы сервера).
"""
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
import structlog

log = structlog.get_logger()

T = TypeVar("T")

from app.constants import RETRY_INITIAL_DELAY_SEC as INITIAL_DELAY_SEC
from app.constants import RETRY_MAX_ATTEMPTS as MAX_ATTEMPTS


async def retry_network(
    operation: Callable[[], Awaitable[T]],
    *,
    label: str,
    max_attempts: int = MAX_ATTEMPTS,
    initial_delay: float = INITIAL_DELAY_SEC,
) -> T:
    """Запускает operation, ретраит httpx.RequestError с exponential backoff.

    Задержки: 1s → 2s → 4s (по умолчанию, max_attempts=3).
    После исчерпания — пробрасывает последнее исключение (вызывающий
    обрабатывает как раньше).
    """
    delay = initial_delay
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except httpx.RequestError as e:
            last_exc = e
            if attempt < max_attempts:
                log.warning(
                    "retry_network_transient",
                    label=label,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    next_delay_sec=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                log.error(
                    "retry_network_exhausted",
                    label=label,
                    attempts=max_attempts,
                    error=str(e),
                    exc_info=True,
                )

    assert last_exc is not None  # гарантировано попаданием сюда
    raise last_exc
