"""Тесты retry_network: backoff на сетевых ошибках и HTTP 429."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.wb_client._retry import retry_network


@pytest.fixture(autouse=True)
def _deterministic_jitter():
    """Jitter: random.uniform → 1.0 (без случайности, задержки предсказуемы)."""
    with patch("app.wb_client._retry.random.uniform", return_value=1.0):
        yield


def _resp(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        request=httpx.Request("GET", "http://x"),
        headers=headers or {},
    )


# --- сетевые ошибки ---


async def test_success_on_first_attempt_no_retries() -> None:
    op = AsyncMock(return_value="ok")
    result = await retry_network(op, label="test")
    assert result == "ok"
    assert op.call_count == 1


async def test_retry_on_network_error_then_success() -> None:
    op = AsyncMock(side_effect=[httpx.ConnectError("transient"), "ok"])
    with patch("app.wb_client._retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_network(op, label="test")
    assert result == "ok"
    assert op.call_count == 2


async def test_all_network_attempts_fail_raises_last() -> None:
    op = AsyncMock(side_effect=httpx.ConnectError("down"))
    with patch("app.wb_client._retry.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.ConnectError):
            await retry_network(op, label="test")
    assert op.call_count == 3


async def test_network_delays_are_exponential() -> None:
    op = AsyncMock(side_effect=httpx.ConnectError("x"))
    sleep_mock = AsyncMock()
    with patch("app.wb_client._retry.asyncio.sleep", new=sleep_mock):
        with pytest.raises(httpx.ConnectError):
            await retry_network(op, label="test")
    delays = [call.args[0] for call in sleep_mock.call_args_list]
    assert delays == [1.0, 2.0]


async def test_non_network_exception_not_retried() -> None:
    op = AsyncMock(side_effect=ValueError("semantic"))
    with pytest.raises(ValueError):
        await retry_network(op, label="test")
    assert op.call_count == 1


# --- 429 rate limit ---


async def test_retry_on_429_then_success() -> None:
    op = AsyncMock(side_effect=[_resp(429), _resp(200)])
    with patch("app.wb_client._retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_network(op, label="test")
    assert result.status_code == 200
    assert op.call_count == 2


async def test_all_429_returns_last_response_after_4_attempts() -> None:
    op = AsyncMock(side_effect=[_resp(429)] * 4)
    with patch("app.wb_client._retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_network(op, label="test")
    assert result.status_code == 429
    assert op.call_count == 4  # RATE_LIMIT_MAX_ATTEMPTS


async def test_429_exponential_backoff() -> None:
    """Без server-hint: 2 → 4 → 8s (3 sleep-а между 4 попытками)."""
    op = AsyncMock(side_effect=[_resp(429)] * 4)
    sleep_mock = AsyncMock()
    with patch("app.wb_client._retry.asyncio.sleep", new=sleep_mock):
        await retry_network(op, label="test")
    delays = [call.args[0] for call in sleep_mock.call_args_list]
    assert delays == [2.0, 4.0, 8.0]


async def test_429_honors_retry_after_header() -> None:
    """Retry-After: 5 → спим 5s, игнорируя exponential backoff."""
    op = AsyncMock(side_effect=[_resp(429, {"Retry-After": "5"}), _resp(200)])
    sleep_mock = AsyncMock()
    with patch("app.wb_client._retry.asyncio.sleep", new=sleep_mock):
        result = await retry_network(op, label="test")
    assert result.status_code == 200
    delays = [call.args[0] for call in sleep_mock.call_args_list]
    assert delays == [5.0]


async def test_429_honors_x_ratelimit_retry_header() -> None:
    """X-Ratelimit-Retry — альтернативный заголовок WB."""
    op = AsyncMock(side_effect=[_resp(429, {"X-Ratelimit-Retry": "3"}), _resp(200)])
    sleep_mock = AsyncMock()
    with patch("app.wb_client._retry.asyncio.sleep", new=sleep_mock):
        await retry_network(op, label="test")
    delays = [call.args[0] for call in sleep_mock.call_args_list]
    assert delays == [3.0]


async def test_429_retry_after_over_cap_falls_back_to_backoff() -> None:
    """Retry-After: 120 (>30 cap) → игнорируем, идём по exponential (2s)."""
    op = AsyncMock(side_effect=[_resp(429, {"Retry-After": "120"}), _resp(200)])
    sleep_mock = AsyncMock()
    with patch("app.wb_client._retry.asyncio.sleep", new=sleep_mock):
        await retry_network(op, label="test")
    delays = [call.args[0] for call in sleep_mock.call_args_list]
    assert delays == [2.0]


async def test_429_retry_after_malformed_falls_back() -> None:
    """Retry-After: abc → игнорируем, exponential backoff."""
    op = AsyncMock(side_effect=[_resp(429, {"Retry-After": "abc"}), _resp(200)])
    sleep_mock = AsyncMock()
    with patch("app.wb_client._retry.asyncio.sleep", new=sleep_mock):
        await retry_network(op, label="test")
    delays = [call.args[0] for call in sleep_mock.call_args_list]
    assert delays == [2.0]


async def test_non_429_4xx_not_retried() -> None:
    """401/500 не ретраим — возвращаем как есть, 1 попытка."""
    op = AsyncMock(return_value=_resp(401))
    result = await retry_network(op, label="test")
    assert result.status_code == 401
    assert op.call_count == 1


async def test_jitter_applied_to_backoff() -> None:
    """С jitter=1.2 задержка 2s → 2.4s."""
    op = AsyncMock(side_effect=[_resp(429), _resp(200)])
    sleep_mock = AsyncMock()
    with patch("app.wb_client._retry.random.uniform", return_value=1.2), \
         patch("app.wb_client._retry.asyncio.sleep", new=sleep_mock):
        await retry_network(op, label="test")
    delays = [call.args[0] for call in sleep_mock.call_args_list]
    assert delays == [pytest.approx(2.4)]
