"""Тесты refresh_seller_lk — мокируем httpx, не делаем реальных запросов."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.wb_client.auth import refresh_seller_lk

# Подтверждённая структура ответа (2026-04-16)
_RESPONSE_200 = {
    "jsonrpc": "2.0",
    "id": "json-rpc_202",
    "result": {
        "data": {
            "token": "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.test_token",
            "userID": 12345678,
            "exp": 1745000000,
        }
    },
}


def _make_mock_client(status_code: int, json_body: dict | None = None, raise_exc: Exception | None = None):
    """Строит мок httpx.AsyncClient для `async with httpx.AsyncClient() as client:`."""
    if raise_exc:
        mock_inner = AsyncMock()
        mock_inner.post = AsyncMock(side_effect=raise_exc)
    else:
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.is_success = (200 <= status_code < 300)
        mock_resp.json = MagicMock(return_value=json_body or {})
        mock_inner = AsyncMock()
        mock_inner.post = AsyncMock(return_value=mock_resp)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


async def test_refresh_success() -> None:
    with patch("app.wb_client.auth.httpx.AsyncClient", return_value=_make_mock_client(200, _RESPONSE_200)):
        result = await refresh_seller_lk("cookie=test", "authorizev3_jwt")

    assert result == "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.test_token"


async def test_refresh_401_returns_none() -> None:
    with patch("app.wb_client.auth.httpx.AsyncClient", return_value=_make_mock_client(401)):
        result = await refresh_seller_lk("cookie=test", "authorizev3_jwt")

    assert result is None


async def test_refresh_500_returns_none() -> None:
    with patch("app.wb_client.auth.httpx.AsyncClient", return_value=_make_mock_client(500, {"error": "server error"})):
        result = await refresh_seller_lk("cookie=test", "authorizev3_jwt")

    assert result is None


async def test_refresh_network_error_returns_none() -> None:
    exc = httpx.ConnectError("connection refused")
    with patch("app.wb_client.auth.httpx.AsyncClient", return_value=_make_mock_client(0, raise_exc=exc)):
        result = await refresh_seller_lk("cookie=test", "authorizev3_jwt")

    assert result is None


async def test_refresh_unexpected_json_structure_returns_none() -> None:
    """Ответ без result.data.token → None."""
    bad_body = {"jsonrpc": "2.0", "result": {}}  # нет "data"
    with patch("app.wb_client.auth.httpx.AsyncClient", return_value=_make_mock_client(200, bad_body)):
        result = await refresh_seller_lk("cookie=test", "authorizev3_jwt")

    assert result is None


async def test_refresh_token_not_string_returns_none() -> None:
    """token — int вместо str → None."""
    bad_body = {
        "jsonrpc": "2.0",
        "result": {"data": {"token": 99999, "userID": 1, "exp": 0}},
    }
    with patch("app.wb_client.auth.httpx.AsyncClient", return_value=_make_mock_client(200, bad_body)):
        result = await refresh_seller_lk("cookie=test", "authorizev3_jwt")

    assert result is None


async def test_token_is_cached_within_ttl() -> None:
    """Второй вызов с теми же креденшелами не должен бить по сети."""
    mock_client = _make_mock_client(200, _RESPONSE_200)
    with patch("app.wb_client.auth.httpx.AsyncClient", return_value=mock_client):
        first = await refresh_seller_lk("cookie=cache_test", "auth_cache_test")
        second = await refresh_seller_lk("cookie=cache_test", "auth_cache_test")

    assert first == second
    # Mock httpx.AsyncClient был задействован только 1 раз (первый refresh)
    assert mock_client.__aenter__.call_count == 1


async def test_invalidate_clears_cache() -> None:
    """invalidate_token_cache() заставляет следующий refresh ходить по сети."""
    from app.wb_client.auth import invalidate_token_cache as clear

    mock_client = _make_mock_client(200, _RESPONSE_200)
    with patch("app.wb_client.auth.httpx.AsyncClient", return_value=mock_client):
        await refresh_seller_lk("cookie=inv_test", "auth_inv_test")
        clear()
        await refresh_seller_lk("cookie=inv_test", "auth_inv_test")

    assert mock_client.__aenter__.call_count == 2


async def test_different_cookies_different_cache_entries() -> None:
    """Смена куки → новый ключ → новый refresh (старая запись не возвращается)."""
    mock_client = _make_mock_client(200, _RESPONSE_200)
    with patch("app.wb_client.auth.httpx.AsyncClient", return_value=mock_client):
        await refresh_seller_lk("cookie=user_A", "auth_A")
        await refresh_seller_lk("cookie=user_B", "auth_B")

    assert mock_client.__aenter__.call_count == 2
