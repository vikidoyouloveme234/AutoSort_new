"""Чтение остатков и квот через ЛК-endpoint'ы (на куках).

Реверс UI seller.wildberries.ru, раздел «Перераспределение остатков»
(2026-04-18). Заменяет официальные Content API + stocks-report —
работает на тех же куках, что и submit_order. Не требует Персонального
токена.
"""
from dataclasses import dataclass

import httpx
import structlog

from app.wb_client._common import STATIC_HEADERS, get_limiter
from app.wb_client.auth import invalidate_token_cache, refresh_seller_lk
from app.wb_client._retry import retry_network

log = structlog.get_logger()

BASE_URL = "https://seller-weekly-report.wildberries.ru/ns/shifts/analytics-back/api/v1"


@dataclass
class WarehouseStock:
    office_id: int
    office_name: str
    chrt_id: int          # first chrtID — для безразмерных товаров их единственный
    count: int            # на этом складе сейчас


async def _build_headers(cookie_str: str, authorizev3: str) -> dict[str, str] | None:
    """Получить свежий wb-seller-lk и сформировать полный набор заголовков."""
    seller_lk = await refresh_seller_lk(cookie_str, authorizev3)
    if seller_lk is None:
        return None
    return {
        **STATIC_HEADERS,
        "authorizev3": authorizev3,
        "wb-seller-lk": seller_lk,
        "Cookie": cookie_str,
    }


async def fetch_stocks_lk(
    nm_id: int,
    cookie_str: str,
    authorizev3: str,
) -> dict[int, WarehouseStock] | None:
    """Возвращает {warehouse_id → WarehouseStock} по nmID.

    Берёт первый chrtID из inStock каждого склада (для безразмерных товаров —
    он единственный). Для многоразмерных пришлось бы расширять структуру.
    None — при сбое API/auth, пустой dict — товара нигде нет.
    """
    headers = await _build_headers(cookie_str, authorizev3)
    if headers is None:
        log.error("lk_stocks_auth_failed")
        return None

    url = f"{BASE_URL}/stocks?nmID={nm_id}"
    async with get_limiter():
        async with httpx.AsyncClient() as client:
            async def _do_get() -> httpx.Response:
                return await client.get(url, headers=headers, timeout=15)
            try:
                resp = await retry_network(_do_get, label="lk_stocks")
            except httpx.RequestError:
                return None

    if resp.status_code == 401:
        # Кэш мог отдать stale-токен раньше TTL — сбрасываем чтобы next call
        # сделал свежий refresh (если куки живые — восстановимся сразу).
        log.warning("lk_stocks_unauthorized_cache_invalidated")
        invalidate_token_cache()
        return None
    if not resp.is_success:
        log.warning("lk_stocks_http_error", status=resp.status_code)
        return None
    try:
        body = resp.json()
    except Exception:
        log.exception("lk_stocks_invalid_json")
        return None
    if body.get("error") is True:
        log.warning("lk_stocks_body_error", error_text=body.get("errorText"))
        return None

    result: dict[int, WarehouseStock] = {}
    for wh in body.get("data", {}).get("src", []) or []:
        try:
            office_id = int(wh["officeID"])
            in_stock = wh.get("inStock", [])
            if not in_stock:
                continue
            first = in_stock[0]
            result[office_id] = WarehouseStock(
                office_id=office_id,
                office_name=str(wh.get("officeName", "")),
                chrt_id=int(first["chrtID"]),
                count=int(first.get("count", 0)),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return result


async def fetch_quota(
    office_id: int,
    quota_type: str,                 # "src" или "dst"
    cookie_str: str,
    authorizev3: str,
) -> int | None:
    """Возвращает текущую дневную квоту склада (сколько ещё может принять/отдать).

    None — при сбое API/auth. 0 — квота исчерпана на сегодня.
    """
    if quota_type not in ("src", "dst"):
        raise ValueError(f"quota_type должен быть 'src' или 'dst', не {quota_type!r}")

    headers = await _build_headers(cookie_str, authorizev3)
    if headers is None:
        log.error("lk_quota_auth_failed")
        return None

    url = f"{BASE_URL}/quota?officeID={office_id}&type={quota_type}"
    async with get_limiter():
        async with httpx.AsyncClient() as client:
            async def _do_get() -> httpx.Response:
                return await client.get(url, headers=headers, timeout=15)
            try:
                resp = await retry_network(_do_get, label="lk_quota")
            except httpx.RequestError:
                return None

    if resp.status_code == 401:
        log.warning("lk_quota_unauthorized_cache_invalidated")
        invalidate_token_cache()
        return None
    if not resp.is_success:
        log.warning("lk_quota_http_error", status=resp.status_code)
        return None
    try:
        body = resp.json()
    except Exception:
        log.exception("lk_quota_invalid_json")
        return None
    if body.get("error") is True:
        log.warning("lk_quota_body_error", error_text=body.get("errorText"))
        return None

    try:
        return int(body["data"]["quota"])
    except (KeyError, TypeError, ValueError):
        log.error("lk_quota_malformed_response")
        return None
