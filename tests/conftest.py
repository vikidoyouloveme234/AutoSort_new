from unittest.mock import AsyncMock, patch

import pytest

from app.sheets import writer
from app.sheets._rate_limit import reset as reset_sheets_limiters
from app.wb_client.auth import invalidate_token_cache


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """Кэш wb-seller-lk — module-level dict, шарится между тестами.
    Чистим перед каждым тестом, иначе моки httpx бесполезны (попадаем в кэш).
    """
    invalidate_token_cache()
    yield
    invalidate_token_cache()


@pytest.fixture(autouse=True)
def _clear_sheets_state():
    """writer._pending и rate-limiter deques — module-level. Чистим между
    тестами чтобы не было перекрёстного загрязнения."""
    writer._pending.clear()
    reset_sheets_limiters()
    yield
    writer._pending.clear()
    reset_sheets_limiters()


@pytest.fixture(autouse=True)
def _fast_retry_sleep():
    """retry_network делает exponential backoff со sleep'ами. В тестах не ждём.
    Патчим только внутри _retry (чтобы не ломать тесты где asyncio.sleep нужен)."""
    with patch("app.wb_client._retry.asyncio.sleep", new=AsyncMock()):
        yield


@pytest.fixture
def known_warehouses() -> set[str]:
    """Справочник складов — 16 значений из листа «Склады»."""
    return {
        "Коледино",
        "Электросталь",
        "Склад Шушары",
        "Краснодар",
        "Екатеринбург - Перспективная 14",
        "Тула",
        "Невинномысск",
        "Рязань (Тюшевское)",
        "Котовск",
        "Самара (Новосемейкино)",
        "Казань",
        "Волгоград",
        "Владимир",
        "Сарапул",
        "Пенза",
        "Новосибирск",
    }
