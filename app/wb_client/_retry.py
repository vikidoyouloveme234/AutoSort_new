"""Retry-обёртка для сетевых вызовов.

Ретраим:
- httpx.RequestError (connection/timeout/сетевой сбой) — 3 попытки, 1→2→4s.
- HTTP 429 Too Many Requests — 4 попытки, 2→4→8→16s (или по Retry-After/
  X-Ratelimit-Retry если сервер подсказал ≤30s).

Все задержки с jitter ±20% — чтобы параллельные таски не синхронизировались
и не ловили повторные 429 волной. Прочие 4xx/5xx НЕ ретраим — это
семантические ответы сервера, их обрабатывает caller.
"""
import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
import structlog

from app.constants import RATE_LIMIT_MAX_ATTEMPTS as RL_MAX_ATTEMPTS
from app.constants import RATE_LIMIT_RETRY_AFTER_CAP_SEC as RL_RETRY_AFTER_CAP
from app.constants import RATE_LIMIT_RETRY_INITIAL_DELAY_SEC as RL_INITIAL_DELAY_SEC
from app.constants import RETRY_INITIAL_DELAY_SEC as INITIAL_DELAY_SEC
from app.constants import RETRY_MAX_ATTEMPTS as MAX_ATTEMPTS

log = structlog.get_logger()

T = TypeVar("T")

_JITTER_RANGE = (0.8, 1.2)


def _jitter(delay: float) -> float:
    return delay * random.uniform(*_JITTER_RANGE)


def _parse_retry_after(resp: httpx.Response) -> float | None:
    """Возвращает число секунд из Retry-After / X-Ratelimit-Retry, иначе None.

    Только целое/дробное число секунд; HTTP-date формат (RFC 7231) у WB
    не встречается — не поддерживаем. Значения >CAP отбрасываем — слишком
    долго ждать имеет смысл, возвращаем 429 вверх, caller пометит задачу
    и следующий цикл разберётся.
    """
    for header in ("Retry-After", "X-Ratelimit-Retry"):
        raw = resp.headers.get(header)
        if not raw:
            continue
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            continue
        if 0 < seconds <= RL_RETRY_AFTER_CAP:
            return seconds
    return None


async def retry_network(
    operation: Callable[[], Awaitable[T]],
    *,
    label: str,
    max_attempts: int = MAX_ATTEMPTS,
    initial_delay: float = INITIAL_DELAY_SEC,
    rate_limit_max_attempts: int = RL_MAX_ATTEMPTS,
    rate_limit_initial_delay: float = RL_INITIAL_DELAY_SEC,
) -> T:
    """Запускает operation с ретраями на сетевых ошибках и HTTP 429."""
    net_delay = initial_delay
    rl_delay = rate_limit_initial_delay
    net_attempts = 0
    rl_attempts = 0
    last_exc: Exception | None = None

    while True:
        try:
            result = await operation()
        except httpx.RequestError as e:
            last_exc = e
            net_attempts += 1
            if net_attempts >= max_attempts:
                log.error(
                    "retry_network_exhausted",
                    label=label,
                    attempts=net_attempts,
                    error=str(e),
                    exc_info=True,
                )
                raise
            log.warning(
                "retry_network_transient",
                label=label,
                attempt=net_attempts,
                max_attempts=max_attempts,
                next_delay_sec=net_delay,
                error=str(e),
            )
            await asyncio.sleep(_jitter(net_delay))
            net_delay *= 2
            continue

        if isinstance(result, httpx.Response) and result.status_code == 429:
            rl_attempts += 1
            if rl_attempts >= rate_limit_max_attempts:
                log.error(
                    "retry_rate_limit_exhausted",
                    label=label,
                    attempts=rl_attempts,
                )
                return result

            server_hint = _parse_retry_after(result)
            if server_hint is not None:
                sleep_for = _jitter(server_hint)
                log.warning(
                    "retry_rate_limit_server_hint",
                    label=label,
                    attempt=rl_attempts,
                    hint_sec=server_hint,
                    sleep_sec=round(sleep_for, 2),
                )
            else:
                sleep_for = _jitter(rl_delay)
                log.warning(
                    "retry_rate_limit",
                    label=label,
                    attempt=rl_attempts,
                    max_attempts=rate_limit_max_attempts,
                    sleep_sec=round(sleep_for, 2),
                )
                rl_delay *= 2
            await asyncio.sleep(sleep_for)
            continue

        return result
