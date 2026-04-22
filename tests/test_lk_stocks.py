"""Тесты для LK-endpoints (stocks/quota через куки)."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.wb_client.lk_stocks import WarehouseStock, fetch_quota, fetch_stocks_lk


def _mock_client(status: int, body: dict):
    resp = MagicMock()
    resp.status_code = status
    resp.is_success = (200 <= status < 300)
    resp.json = MagicMock(return_value=body)

    inner = AsyncMock()
    inner.get = AsyncMock(return_value=resp)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ----- fetch_stocks_lk -----

async def test_stocks_parses_two_warehouses() -> None:
    body = {
        "data": {
            "src": [
                {"officeID": 206348, "officeName": "Тула",
                 "inStock": [{"chrtID": 627675086, "count": 72, "techSize": "37"}]},
                {"officeID": 120762, "officeName": "Электросталь",
                 "inStock": [{"chrtID": 627675086, "count": 54, "techSize": "37"}]},
            ]
        },
        "error": False,
    }
    with (
        patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value="lk_token")),
        patch("app.wb_client.lk_stocks.httpx.AsyncClient", return_value=_mock_client(200, body)),
    ):
        stocks = await fetch_stocks_lk(443589786, "cookie=test", "auth")

    assert stocks is not None
    assert len(stocks) == 2
    assert stocks[206348] == WarehouseStock(
        office_id=206348, office_name="Тула", chrt_id=627675086, count=72,
    )
    assert stocks[120762].count == 54


async def test_stocks_empty_warehouse_skipped() -> None:
    body = {"data": {"src": [{"officeID": 999, "inStock": []}]}, "error": False}
    with (
        patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value="lk_token")),
        patch("app.wb_client.lk_stocks.httpx.AsyncClient", return_value=_mock_client(200, body)),
    ):
        stocks = await fetch_stocks_lk(123, "cookie=test", "auth")
    assert stocks == {}


async def test_stocks_auth_fail_returns_none() -> None:
    with patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value=None)):
        result = await fetch_stocks_lk(123, "cookie=test", "auth")
    assert result is None


async def test_stocks_body_error_returns_none() -> None:
    body = {"data": None, "error": True, "errorText": "someError"}
    with (
        patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value="lk_token")),
        patch("app.wb_client.lk_stocks.httpx.AsyncClient", return_value=_mock_client(200, body)),
    ):
        result = await fetch_stocks_lk(123, "cookie=test", "auth")
    assert result is None


async def test_stocks_network_error_returns_none() -> None:
    inner = AsyncMock()
    inner.get = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value="lk_token")),
        patch("app.wb_client.lk_stocks.httpx.AsyncClient", return_value=cm),
    ):
        result = await fetch_stocks_lk(123, "cookie=test", "auth")
    assert result is None


# ----- fetch_quota -----

async def test_quota_returns_int() -> None:
    body = {"data": {"officeID": 130744, "quota": 39932}, "error": False}
    with (
        patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value="lk_token")),
        patch("app.wb_client.lk_stocks.httpx.AsyncClient", return_value=_mock_client(200, body)),
    ):
        q = await fetch_quota(130744, "src", "cookie=test", "auth")
    assert q == 39932


async def test_quota_invalid_type_raises() -> None:
    with pytest.raises(ValueError):
        await fetch_quota(1, "wrong", "cookie", "auth")


async def test_quota_auth_fail_returns_none() -> None:
    with patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value=None)):
        result = await fetch_quota(1, "src", "cookie", "auth")
    assert result is None


async def test_quota_malformed_returns_none() -> None:
    body = {"data": {"officeID": 1}, "error": False}  # нет поля quota
    with (
        patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value="lk_token")),
        patch("app.wb_client.lk_stocks.httpx.AsyncClient", return_value=_mock_client(200, body)),
    ):
        result = await fetch_quota(1, "src", "cookie", "auth")
    assert result is None


# ----- 401 → инвалидация кэша токена -----

async def test_stocks_401_invalidates_token_cache() -> None:
    """401 от /stocks → cache cleared, чтобы next call пошёл за свежим токеном."""
    invalidate_calls = MagicMock()
    with (
        patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value="lk_token")),
        patch("app.wb_client.lk_stocks.httpx.AsyncClient", return_value=_mock_client(401, {})),
        patch("app.wb_client.lk_stocks.invalidate_token_cache", side_effect=invalidate_calls),
    ):
        result = await fetch_stocks_lk(123, "cookie=test", "auth")

    assert result is None
    invalidate_calls.assert_called_once()


async def test_quota_401_invalidates_token_cache() -> None:
    """То же самое для /quota."""
    invalidate_calls = MagicMock()
    with (
        patch("app.wb_client.lk_stocks.refresh_seller_lk", new=AsyncMock(return_value="lk_token")),
        patch("app.wb_client.lk_stocks.httpx.AsyncClient", return_value=_mock_client(401, {})),
        patch("app.wb_client.lk_stocks.invalidate_token_cache", side_effect=invalidate_calls),
    ):
        result = await fetch_quota(1, "src", "cookie", "auth")

    assert result is None
    invalidate_calls.assert_called_once()
