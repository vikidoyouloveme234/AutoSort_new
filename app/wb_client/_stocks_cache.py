"""In-memory TTL-кэш для fetch_stocks_lk.

Midnight rush: на 50 строк Sheets с повторяющимися nmID без кэша — 50
запросов подряд к /stocks, легко ловим 429. С кэшем на 2 минуты —
запросов по числу уникальных nmID.

Baseline при cache-hit немного устаревший (до TTL сек), но watcher с
этим справляется: при просчёте delta = current - baseline несколько
единиц погрешности не поменяют решение «приехало / не приехало».

Кэшируются и успешные словари, и пустые ({} = nmID нигде нет). Failure
(None) не кэшируется — чтобы транзиентные сбои не залипали.
"""
import asyncio
from datetime import datetime, timedelta

import structlog

from app.constants import STOCKS_CACHE_TTL_SEC
from app.wb_client.lk_stocks import WarehouseStock, fetch_stocks_lk

log = structlog.get_logger()

# NB: _lock удерживается на время HTTP-запроса. Для текущей последовательной
# обработки в process_once это безопасно (одна task за раз). Если в будущем
# запараллелим — разные nm_id будут зря блокировать друг друга; тогда надо
# переходить на per-key locks (dict[nm_id, Lock]).
_cache: dict[int, tuple[dict[int, WarehouseStock], datetime]] = {}
_lock = asyncio.Lock()


def invalidate_stocks_cache() -> None:
    """Полный сброс (для тестов и на случай сброса сессии)."""
    _cache.clear()


async def fetch_stocks_lk_cached(
    nm_id: int,
    cookie_str: str,
    authorizev3: str,
) -> dict[int, WarehouseStock] | None:
    """Обёртка над fetch_stocks_lk с TTL-кэшем по nm_id."""
    now = datetime.now()

    cached = _cache.get(nm_id)
    if cached is not None and cached[1] > now:
        return cached[0]

    async with _lock:
        # re-check под локом (другая корутина могла уже заполнить)
        cached = _cache.get(nm_id)
        if cached is not None and cached[1] > now:
            return cached[0]

        stocks = await fetch_stocks_lk(nm_id, cookie_str, authorizev3)
        if stocks is None:
            return None
        _cache[nm_id] = (stocks, now + timedelta(seconds=STOCKS_CACHE_TTL_SEC))
        return stocks
