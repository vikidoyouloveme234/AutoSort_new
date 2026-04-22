"""Получение свежего wb-seller-lk через refresh-endpoint.

Подтверждено cURL 2026-04-16:
  POST https://seller.wildberries.ru/ns/suppliers-auth/suppliers-portal-core/auth/token
  Body: {"params":{},"jsonrpc":"2.0","id":"json-rpc_202"}
  Требует: authorizev3 + Cookie (с WBTokenV3 внутри)
  Возвращает JSON с полем, содержащим новый wb-seller-lk (5 мин TTL)

Токен кэшируется на 4 минуты (см. _CACHE_TTL_SEC) — все клиенты в одном процессе
переиспользуют валидный токен. Это критично для midnight rush: иначе на каждую
заявку идёт 3 refresh-запроса (stocks + quota + submit), и rate-limit съедает
всё окно слотов.
"""
import asyncio
import hashlib
from datetime import datetime, timedelta

import httpx
import structlog

log = structlog.get_logger()

# Токен от WB живёт 5 мин — кэшируем на 4, чтобы не вернуть в момент истечения
from app.constants import SELLER_LK_CACHE_TTL_SEC as _CACHE_TTL_SEC  # noqa: E402

# (key → (token, expires_at)). Key = sha256(cookie + authorizev3) — учитывает смену куки.
_token_cache: dict[str, tuple[str, datetime]] = {}
_cache_lock = asyncio.Lock()

TOKEN_URL = (
    "https://seller.wildberries.ru"
    "/ns/suppliers-auth/suppliers-portal-core/auth/token"
)

_TOKEN_STATIC_HEADERS = {
    "accept": "*/*",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "max-age=0",
    "content-type": "application/json",
    "origin": "https://seller.wildberries.ru",
    "referer": "https://seller.wildberries.ru/",
    "root-version": "v1.88.0",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",  # отличается от order (там same-site)
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}

_JSONRPC_BODY = {"params": {}, "jsonrpc": "2.0", "id": "json-rpc_202"}


def _cache_key(cookie_str: str, authorizev3: str) -> str:
    return hashlib.sha256(f"{cookie_str}:{authorizev3}".encode()).hexdigest()


def invalidate_token_cache() -> None:
    """Сбросить кэш токенов (например, после явной 401-ошибки)."""
    _token_cache.clear()


async def refresh_seller_lk(
    cookie_str: str,
    authorizev3: str,
) -> str | None:
    """Получает свежий wb-seller-lk токен (с in-process кэшем на 4 мин).

    Возвращает строку токена или None при ошибке.
    Не логирует authorizev3 и cookie_str.
    """
    key = _cache_key(cookie_str, authorizev3)
    now = datetime.now()

    # Быстрый путь без блокировки — если кэш свежий, отдаём
    cached = _token_cache.get(key)
    if cached is not None and cached[1] > now:
        return cached[0]

    # Медленный путь под лок — чтобы параллельные вызовы не дублировали refresh
    async with _cache_lock:
        cached = _token_cache.get(key)
        if cached is not None and cached[1] > now:
            return cached[0]

        token = await _do_refresh(cookie_str, authorizev3)
        if token is not None:
            _token_cache[key] = (token, now + timedelta(seconds=_CACHE_TTL_SEC))
        return token


async def _do_refresh(cookie_str: str, authorizev3: str) -> str | None:
    """Реальный HTTP-запрос за свежим токеном (без кэша)."""
    headers = {
        **_TOKEN_STATIC_HEADERS,
        "authorizev3": authorizev3,
        "Cookie": cookie_str,
    }

    from app.wb_client._retry import retry_network

    async with httpx.AsyncClient() as client:
        async def _do_post() -> httpx.Response:
            return await client.post(TOKEN_URL, json=_JSONRPC_BODY, headers=headers, timeout=10)
        try:
            resp = await retry_network(_do_post, label="token_refresh")
        except httpx.RequestError:
            return None

    if resp.status_code == 401:
        log.error("token_refresh_unauthorized")
        return None
    if not resp.is_success:
        log.error("token_refresh_failed", status=resp.status_code)
        return None

    data = resp.json()

    # Структура ответа подтверждена 2026-04-16:
    # {"jsonrpc":"2.0","id":"...","result":{"data":{"token":"<jwt>","userID":...,"exp":...}}}
    try:
        token = data["result"]["data"]["token"]
    except (KeyError, TypeError):
        log.error("token_refresh_unexpected_response", keys=list(data.keys()))
        return None

    if not isinstance(token, str):
        log.error("token_refresh_bad_type", type=type(token).__name__)
        return None

    log.info("token_refreshed")
    return token
