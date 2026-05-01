"""Тесты with_retry для Sheets API."""
from unittest.mock import MagicMock, patch

import pytest
from gspread.exceptions import APIError

from app.sheets._rate_limit import with_retry


def _api_error(code: int, headers: dict | None = None) -> APIError:
    """Конструируем APIError максимально близко к реальному gspread."""
    response = MagicMock()
    response.status_code = code
    response.headers = headers or {}
    e = APIError(response)
    # gspread иногда выставляет .code напрямую
    e.code = code  # type: ignore[attr-defined]
    return e


@pytest.fixture(autouse=True)
def _no_sleep():
    """Не ждём реально в тестах."""
    with patch("app.sheets._rate_limit.time.sleep"), \
         patch("app.sheets._rate_limit.random.uniform", return_value=1.0):
        yield


def test_success_first_try_no_retry() -> None:
    op = MagicMock(return_value="ok")
    assert with_retry("test", op) == "ok"
    assert op.call_count == 1


def test_429_retries_then_succeeds() -> None:
    op = MagicMock(side_effect=[_api_error(429), "ok"])
    assert with_retry("test", op) == "ok"
    assert op.call_count == 2


def test_429_exhausts_after_max_attempts() -> None:
    op = MagicMock(side_effect=[_api_error(429)] * 4)  # SHEETS_MAX_ATTEMPTS=4
    with pytest.raises(APIError):
        with_retry("test", op)
    assert op.call_count == 4


def test_429_honors_retry_after_header() -> None:
    op = MagicMock(side_effect=[_api_error(429, headers={"Retry-After": "3"}), "ok"])
    sleep_mock = MagicMock()
    with patch("app.sheets._rate_limit.time.sleep", sleep_mock):
        with_retry("test", op)
    delays = [c.args[0] for c in sleep_mock.call_args_list]
    assert delays == [3.0]


def test_500_retries() -> None:
    op = MagicMock(side_effect=[_api_error(503), "ok"])
    assert with_retry("test", op) == "ok"
    assert op.call_count == 2


def test_401_not_retried() -> None:
    op = MagicMock(side_effect=_api_error(401))
    with pytest.raises(APIError):
        with_retry("test", op)
    assert op.call_count == 1


def test_403_not_retried() -> None:
    op = MagicMock(side_effect=_api_error(403))
    with pytest.raises(APIError):
        with_retry("test", op)
    assert op.call_count == 1


def test_400_not_retried() -> None:
    """Прочие 4xx — не ретраим (семантическая ошибка)."""
    op = MagicMock(side_effect=_api_error(400))
    with pytest.raises(APIError):
        with_retry("test", op)
    assert op.call_count == 1


def test_non_api_error_propagates_without_retry() -> None:
    """Не-APIError (network, JSON parse, и т.д.) — не ретраится, пробрасывается."""
    op = MagicMock(side_effect=ValueError("transport error"))
    with pytest.raises(ValueError):
        with_retry("test", op)
    assert op.call_count == 1
