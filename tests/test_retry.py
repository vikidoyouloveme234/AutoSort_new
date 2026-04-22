"""Тесты retry_network: exponential backoff на сетевых ошибках."""
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.wb_client._retry import retry_network


async def test_success_on_first_attempt_no_retries() -> None:
    """Если operation не падает — возвращаем результат без задержки."""
    op = AsyncMock(return_value="ok")
    result = await retry_network(op, label="test")
    assert result == "ok"
    assert op.call_count == 1


async def test_retry_on_network_error_then_success() -> None:
    """Первый вызов падает сетью, второй — успех."""
    op = AsyncMock(side_effect=[httpx.ConnectError("transient"), "ok"])
    with patch("app.wb_client._retry.asyncio.sleep", new=AsyncMock()):
        result = await retry_network(op, label="test")
    assert result == "ok"
    assert op.call_count == 2


async def test_all_attempts_fail_raises_last() -> None:
    """3 попытки все падают сетью — пробрасываем последнее исключение."""
    op = AsyncMock(side_effect=httpx.ConnectError("down"))
    with patch("app.wb_client._retry.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.ConnectError):
            await retry_network(op, label="test")
    assert op.call_count == 3


async def test_delays_are_exponential() -> None:
    """1s → 2s (между попытками)."""
    op = AsyncMock(side_effect=httpx.ConnectError("x"))
    sleep_mock = AsyncMock()
    with patch("app.wb_client._retry.asyncio.sleep", new=sleep_mock):
        with pytest.raises(httpx.ConnectError):
            await retry_network(op, label="test")
    # 3 попытки, 2 sleep-а между ними: 1, 2
    delays = [call.args[0] for call in sleep_mock.call_args_list]
    assert delays == [1.0, 2.0]


async def test_non_network_exception_not_retried() -> None:
    """ValueError (не RequestError) не ретраим — пробрасываем сразу."""
    op = AsyncMock(side_effect=ValueError("semantic"))
    with pytest.raises(ValueError):
        await retry_network(op, label="test")
    assert op.call_count == 1
