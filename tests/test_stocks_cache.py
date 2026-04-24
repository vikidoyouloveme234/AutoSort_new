"""Тесты in-memory TTL-кэша /stocks."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.wb_client._stocks_cache import fetch_stocks_lk_cached, invalidate_stocks_cache
from app.wb_client.lk_stocks import WarehouseStock


def _stock(chrt_id: int = 100, count: int = 5) -> dict[int, WarehouseStock]:
    return {
        507: WarehouseStock(office_id=507, office_name="Коледино",
                            chrt_id=chrt_id, count=count),
    }


async def test_first_call_hits_underlying_fetch() -> None:
    """Первый вызов — реальный fetch_stocks_lk."""
    mock_fetch = AsyncMock(return_value=_stock())
    with patch("app.wb_client._stocks_cache.fetch_stocks_lk", new=mock_fetch):
        result = await fetch_stocks_lk_cached(12345, "cookie", "auth")
    assert result == _stock()
    assert mock_fetch.call_count == 1


async def test_second_call_uses_cache() -> None:
    """Второй вызов с тем же nm_id — cache hit, fetch не дёргаем."""
    mock_fetch = AsyncMock(return_value=_stock())
    with patch("app.wb_client._stocks_cache.fetch_stocks_lk", new=mock_fetch):
        await fetch_stocks_lk_cached(12345, "cookie", "auth")
        await fetch_stocks_lk_cached(12345, "cookie", "auth")
    assert mock_fetch.call_count == 1


async def test_different_nm_ids_cached_separately() -> None:
    """Разные nm_id — разные ключи кэша, fetch на каждый."""
    mock_fetch = AsyncMock(side_effect=[_stock(100), _stock(200)])
    with patch("app.wb_client._stocks_cache.fetch_stocks_lk", new=mock_fetch):
        r1 = await fetch_stocks_lk_cached(111, "cookie", "auth")
        r2 = await fetch_stocks_lk_cached(222, "cookie", "auth")
    assert r1 != r2
    assert mock_fetch.call_count == 2


async def test_none_result_not_cached() -> None:
    """fetch вернул None (API сдох) — не кэшируем. Следующий вызов — снова fetch."""
    mock_fetch = AsyncMock(side_effect=[None, _stock()])
    with patch("app.wb_client._stocks_cache.fetch_stocks_lk", new=mock_fetch):
        r1 = await fetch_stocks_lk_cached(12345, "cookie", "auth")
        r2 = await fetch_stocks_lk_cached(12345, "cookie", "auth")
    assert r1 is None
    assert r2 == _stock()
    assert mock_fetch.call_count == 2


async def test_empty_dict_is_cached() -> None:
    """{} (nmID нигде нет) — валидный ответ, кэшируем. Следующий вызов — cache hit."""
    mock_fetch = AsyncMock(return_value={})
    with patch("app.wb_client._stocks_cache.fetch_stocks_lk", new=mock_fetch):
        await fetch_stocks_lk_cached(12345, "cookie", "auth")
        await fetch_stocks_lk_cached(12345, "cookie", "auth")
    assert mock_fetch.call_count == 1


async def test_expired_cache_refetches() -> None:
    """Cache expired (TTL истёк) — новый fetch."""
    mock_fetch = AsyncMock(return_value=_stock())
    with patch("app.wb_client._stocks_cache.fetch_stocks_lk", new=mock_fetch):
        await fetch_stocks_lk_cached(12345, "cookie", "auth")

        # Сдвигаем expires_at в прошлое
        from app.wb_client import _stocks_cache as mod
        stocks, _ = mod._cache[12345]
        mod._cache[12345] = (stocks, datetime.now() - timedelta(seconds=1))

        await fetch_stocks_lk_cached(12345, "cookie", "auth")
    assert mock_fetch.call_count == 2


async def test_invalidate_clears_all() -> None:
    """invalidate_stocks_cache сбрасывает всё."""
    mock_fetch = AsyncMock(return_value=_stock())
    with patch("app.wb_client._stocks_cache.fetch_stocks_lk", new=mock_fetch):
        await fetch_stocks_lk_cached(12345, "cookie", "auth")
        invalidate_stocks_cache()
        await fetch_stocks_lk_cached(12345, "cookie", "auth")
    assert mock_fetch.call_count == 2
