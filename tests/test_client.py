"""Тесты submit_order: dry-run и мок-HTTP для реальных путей."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.wb_client.client import OrderRequest, submit_order

_ORDER = OrderRequest(
    src_warehouse_id=130744,   # Краснодар (из живого cURL)
    dst_warehouse_id=208277,   # Невинномысск
    nm_id=292197811,
    chrt_id=734825801,
    count=5,
)


def _make_mock_client(status_code: int, json_body: dict):
    """Строит мок httpx.AsyncClient для `async with httpx.AsyncClient() as client:`."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.is_success = (200 <= status_code < 300)
    mock_resp.json = MagicMock(return_value=json_body)

    mock_inner = AsyncMock()
    mock_inner.post = AsyncMock(return_value=mock_resp)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


# ---------------------------------------------------------------------------
# Dry-run (WB_DRY_RUN=true из .env — HTTP не отправляется)
# ---------------------------------------------------------------------------

async def test_dry_run_returns_success_without_http() -> None:
    """В dry-run режиме: success=True, body={"dry_run": True}, без HTTP."""
    # settings.wb_dry_run=True уже прописан в .env
    resp = await submit_order(_ORDER, "cookie=test", "auth_token")

    assert resp.success is True
    assert resp.status_code == 200
    assert resp.body == {"dry_run": True}


# ---------------------------------------------------------------------------
# Не-dry-run пути (патчим settings.wb_dry_run=False)
# ---------------------------------------------------------------------------

async def test_token_refresh_fail_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """refresh_seller_lk вернул None → OrderResponse(401)."""
    monkeypatch.setattr("app.wb_client.client.settings.wb_dry_run", False)

    with patch("app.wb_client.auth.refresh_seller_lk", new=AsyncMock(return_value=None)):
        resp = await submit_order(_ORDER, "cookie=test", "auth_token")

    assert resp.success is False
    assert resp.status_code == 401
    assert resp.body["error"] == "token_refresh_failed"


async def test_wb_200_returns_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.wb_client.client.settings.wb_dry_run", False)

    with (
        patch("app.wb_client.auth.refresh_seller_lk", new=AsyncMock(return_value="fresh_token")),
        patch("app.wb_client.client.httpx.AsyncClient", return_value=_make_mock_client(200, {"result": "ok"})),
    ):
        resp = await submit_order(_ORDER, "cookie=test", "auth_token")

    assert resp.success is True
    assert resp.status_code == 200


async def test_wb_401_returns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.wb_client.client.settings.wb_dry_run", False)

    body = {"error": "Unauthorized", "message": "Cookie expired or invalid"}
    with (
        patch("app.wb_client.auth.refresh_seller_lk", new=AsyncMock(return_value="fresh_token")),
        patch("app.wb_client.client.httpx.AsyncClient", return_value=_make_mock_client(401, body)),
    ):
        resp = await submit_order(_ORDER, "cookie=test", "auth_token")

    assert resp.success is False
    assert resp.status_code == 401


async def test_wb_429_returns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.wb_client.client.settings.wb_dry_run", False)

    body = {"error": "Too Many Requests", "message": "Rate limit exceeded"}
    with (
        patch("app.wb_client.auth.refresh_seller_lk", new=AsyncMock(return_value="fresh_token")),
        patch("app.wb_client.client.httpx.AsyncClient", return_value=_make_mock_client(429, body)),
    ):
        resp = await submit_order(_ORDER, "cookie=test", "auth_token")

    assert resp.success is False
    assert resp.status_code == 429


async def test_wb_200_with_body_error_is_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """WB иногда отдаёт HTTP 200, но body.error=true (nmError, requestAlreadyInProcess и т.п.).

    Должны вернуть success=False, иначе task_processor пометит строку IN_QUEUE
    и watcher будет вечно ждать товар, который никогда не приедет.
    """
    monkeypatch.setattr("app.wb_client.client.settings.wb_dry_run", False)

    body = {"data": {"success": False}, "error": True, "errorText": "nmError"}
    with (
        patch("app.wb_client.auth.refresh_seller_lk", new=AsyncMock(return_value="fresh_token")),
        patch("app.wb_client.client.httpx.AsyncClient", return_value=_make_mock_client(200, body)),
    ):
        resp = await submit_order(_ORDER, "cookie=test", "auth_token")

    assert resp.success is False
    assert resp.status_code == 200
    assert resp.body["errorText"] == "nmError"


async def test_wb_500_returns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.wb_client.client.settings.wb_dry_run", False)

    with (
        patch("app.wb_client.auth.refresh_seller_lk", new=AsyncMock(return_value="fresh_token")),
        patch("app.wb_client.client.httpx.AsyncClient", return_value=_make_mock_client(500, {"error": "Internal Server Error"})),
    ):
        resp = await submit_order(_ORDER, "cookie=test", "auth_token")

    assert resp.success is False
    assert resp.status_code == 500


async def test_wb_network_error_returns_status_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сетевая ошибка (timeout/connect) → status_code=0, не 5xx. Сигнал processor'у повторить."""
    monkeypatch.setattr("app.wb_client.client.settings.wb_dry_run", False)

    mock_inner = AsyncMock()
    mock_inner.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.wb_client.auth.refresh_seller_lk", new=AsyncMock(return_value="fresh_token")),
        patch("app.wb_client.client.httpx.AsyncClient", return_value=mock_cm),
    ):
        resp = await submit_order(_ORDER, "cookie=test", "auth_token")

    assert resp.success is False
    assert resp.status_code == 0
    assert resp.body["error"] == "network"
