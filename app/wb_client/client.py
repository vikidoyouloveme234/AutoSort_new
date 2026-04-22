"""HTTP-клиент для WB неофициального API перераспределения остатков.

Подтверждено cURL от заказчика 2026-04-16:
- Заголовок авторизации: authorizev3 (строчные)
- Заголовок сессии: wb-seller-lk (строчные через дефис, TTL 5 мин)
- Куки передаются через Cookie header
- Warehouse ID из FBW API совпадают с ID в этом endpoint

ВАЖНО: никогда не логировать authorizev3, wb-seller-lk и Cookie.
В DRY_RUN режиме запрос не отправляется.
"""
from dataclasses import dataclass

import httpx
import structlog

from app.config import settings
from app.wb_client._common import STATIC_HEADERS, get_limiter

log = structlog.get_logger()

BASE_URL = "https://seller-weekly-report.wildberries.ru/ns/shifts/analytics-back/api/v1/order"


@dataclass
class OrderRequest:
    src_warehouse_id: int
    dst_warehouse_id: int
    nm_id: int
    chrt_id: int
    count: int


@dataclass
class OrderResponse:
    success: bool
    status_code: int
    body: dict[str, object]


async def submit_order(
    order: OrderRequest,
    decrypted_cookie: str,   # Cookie header целиком (включая WBTokenV3)
    authorizev3: str,        # долгоживущий JWT
) -> OrderResponse:
    """Отправить заявку на перераспределение остатков.

    Перед отправкой автоматически получает свежий wb-seller-lk через /auth/token.
    В DRY_RUN режиме логирует параметры и возвращает success=True без HTTP.
    """
    from app.wb_client.auth import refresh_seller_lk

    payload = {
        "order": {
            "src": order.src_warehouse_id,
            "dst": order.dst_warehouse_id,
            "nmID": order.nm_id,
            "count": [{"chrtID": order.chrt_id, "count": order.count}],
        }
    }

    if settings.wb_dry_run:
        log.info(
            "dry_run_order",
            nm_id=order.nm_id,
            src=order.src_warehouse_id,
            dst=order.dst_warehouse_id,
            count=order.count,
        )
        return OrderResponse(success=True, status_code=200, body={"dry_run": True})

    # Circuit breaker: если недавно много подряд фейлов — не идём в WB
    from app.wb_client._circuit import is_open as circuit_is_open
    from app.wb_client._circuit import record_failure, record_success

    if circuit_is_open():
        log.warning("circuit_breaker_open_skip_submit")
        return OrderResponse(
            success=False, status_code=0,
            body={"error": "circuit_breaker_open", "detail": "WB cooldown after repeated failures"},
        )

    # Получаем свежий wb-seller-lk (TTL 5 мин)
    seller_lk = await refresh_seller_lk(decrypted_cookie, authorizev3)
    if seller_lk is None:
        return OrderResponse(success=False, status_code=401, body={"error": "token_refresh_failed"})

    headers = {
        **STATIC_HEADERS,
        "authorizev3": authorizev3,
        "wb-seller-lk": seller_lk,
        "Cookie": decrypted_cookie,
    }

    from app.wb_client._retry import retry_network

    async with get_limiter():
        async with httpx.AsyncClient() as client:
            async def _do_post() -> httpx.Response:
                return await client.post(BASE_URL, json=payload, headers=headers, timeout=10)
            try:
                resp = await retry_network(_do_post, label="submit_order")
            except httpx.RequestError as e:
                # 3 попытки исчерпаны. status_code=0 → task_processor оставит
                # строку «Создан» и следующий цикл повторит (уже на уровне batch-loop).
                record_failure()
                return OrderResponse(
                    success=False,
                    status_code=0,
                    body={"error": "network", "detail": str(e)},
                )

    if resp.status_code == 429:
        log.warning("wb_rate_limited")
    elif resp.status_code == 401:
        log.error("wb_unauthorized")
    elif not resp.is_success:
        log.error("wb_request_failed", status=resp.status_code)

    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}

    # WB иногда возвращает 200 OK с body.error=true (например, nmError, requestAlreadyInProcess).
    # Доверяем body.error больше, чем HTTP-коду — это ИСТИННЫЙ индикатор успеха у WB.
    body_says_error = isinstance(body, dict) and body.get("error") is True
    real_success = resp.is_success and not body_says_error

    if real_success is False and resp.is_success:
        log.warning("wb_200_with_body_error", error_text=body.get("errorText"))

    # Обновляем circuit breaker: 5xx считается фейлом системы, 4xx — нет (логика WB)
    if resp.status_code >= 500:
        record_failure()
    else:
        record_success()

    return OrderResponse(
        success=real_success,
        status_code=resp.status_code,
        body=body,
    )
