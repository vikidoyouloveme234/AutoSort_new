"""Общие утилиты для wb_client модулей: статические заголовки, rate limiter.

Вынесено из client.py чтобы lk_stocks.py не импортировал приватные _STATIC_HEADERS
и _get_limiter (underscore нарушало конвенцию).
"""
import asyncio

from aiolimiter import AsyncLimiter

from app.constants import WB_RATE_LIMIT_PERIOD_SEC, WB_RATE_LIMIT_RPS

# Статические заголовки для всех WB-запросов через куки.
# Подтверждено cURL из ЛК 2026-04-16.
STATIC_HEADERS = {
    "accept": "*/*",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://seller.wildberries.ru",
    "referer": "https://seller.wildberries.ru/",
    "root-version": "v1.88.0",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}

# Rate limiter — единый инстанс на все WB-запросы (submit + stocks + quota),
# чтобы суммарно не превышать реальный лимит WB. Probe 2026-04-28 показал:
# 1 req/s — без 429, 2 req/s — 10% брака, 3 req/s — 60% брака. Сейчас 2 req/s
# (cм. WB_RATE_LIMIT_RPS в app/constants.py). Пересоздаётся при смене event
# loop (актуально для pytest).
_limiter: AsyncLimiter | None = None
_limiter_loop: asyncio.AbstractEventLoop | None = None


def get_limiter() -> AsyncLimiter:
    global _limiter, _limiter_loop
    try:
        current_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    if _limiter is None or _limiter_loop is not current_loop:
        _limiter = AsyncLimiter(max_rate=WB_RATE_LIMIT_RPS, time_period=WB_RATE_LIMIT_PERIOD_SEC)
        _limiter_loop = current_loop
    return _limiter
