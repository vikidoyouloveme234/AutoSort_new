"""Сервис хранения и расшифровки WB-куков.

Куки хранятся в БД зашифрованными через Fernet.
Никогда не логировать расшифрованные значения.
"""
import json
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.cookie import WbCookie

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.fernet_key.encode())
    return _fernet


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


async def get_active_cookie(session: AsyncSession) -> WbCookie | None:
    result = await session.execute(
        select(WbCookie)
        .where(WbCookie.is_active.is_(True))
        .order_by(WbCookie.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_decrypted_credentials(session: AsyncSession) -> tuple[str, str] | None:
    """Возвращает (cookie_str, authorizev3) или None если нет активного куки."""
    cookie_row = await get_active_cookie(session)
    if cookie_row is None:
        return None
    try:
        cookie_str = decrypt(cookie_row.encrypted_cookie)
        authorizev3 = ""
        if cookie_row.encrypted_headers:
            headers = json.loads(decrypt(cookie_row.encrypted_headers))
            authorizev3 = headers.get("authorizev3", "")
        return cookie_str, authorizev3
    except InvalidToken:
        return None


# Динамические куки, которые WB/Cloudflare ротируют каждые час-два.
# Endpoint /stocks, /quota, /order их не проверяют (тестировано 2026-04-22).
# Фильтруем при сохранении — иначе бот через 2 часа начнёт получать 401
# от stocks (refresh продолжает работать, но stocks/quota — нет).
_TRANSIENT_COOKIES = frozenset({
    "cfidsw-wb",      # Cloudflare bot management — ротируется
    "__zzatw-wb",     # ZooZoo (Wallarm/akamai-style anti-bot) — ротируется
    "_ga", "_ga_TXRZMJQDFE", "_wbauid",  # аналитика, не нужны
    "external-locale", # тривиальная локаль
})


def _strip_transient_cookies(cookie_str: str) -> str:
    """Оставляет только стабильные куки (WBTokenV3, x-supplier-id, validation-key)."""
    parts = []
    for chunk in cookie_str.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name = chunk.split("=", 1)[0].strip()
        if name in _TRANSIENT_COOKIES:
            continue
        parts.append(chunk)
    return "; ".join(parts)


async def save_cookie(
    session: AsyncSession,
    cookie_str: str,
    headers: dict[str, str] | None = None,
) -> WbCookie:
    # headers ожидает {"authorizev3": "..."}
    """Шифрует и сохраняет новый куки. Деактивирует предыдущие.

    Фильтрует динамические anti-bot куки (cfidsw-wb, __zzatw-wb) которые
    ротируются каждые час-два — их не нужно хранить, иначе бот будет ловить
    401 на stocks/quota когда WB обновит anti-bot cookie.
    """
    cookie_str = _strip_transient_cookies(cookie_str)

    # Деактивируем старые
    old = await session.execute(select(WbCookie).where(WbCookie.is_active.is_(True)))
    for row in old.scalars():
        row.is_active = False

    new_cookie = WbCookie(
        encrypted_cookie=encrypt(cookie_str),
        encrypted_headers=encrypt(json.dumps(headers)) if headers else None,
        is_active=True,
        health="ok",
    )
    session.add(new_cookie)
    await session.commit()
    await session.refresh(new_cookie)
    return new_cookie


async def check_cookie_health(session: AsyncSession) -> str:
    """Пробует обновить wb-seller-lk через сохранённые куки.

    Возвращает 'ok' / 'expired' / 'no_cookie'.
    При 'ok' — обновляет last_verified_at (внутри mark_cookie_health).
    """
    from app.wb_client.auth import refresh_seller_lk

    creds = await get_decrypted_credentials(session)
    if creds is None:
        return "no_cookie"
    cookie_str, authorizev3 = creds
    token = await refresh_seller_lk(cookie_str, authorizev3)
    health = "ok" if token else "expired"
    await mark_cookie_health(session, health)
    return health


async def mark_cookie_health(session: AsyncSession, health: str) -> None:
    """Обновляет статус проверки куки: 'ok' / 'expired' / 'unknown'.

    При health='ok' также обновляет last_verified_at — фиксирует момент
    реального подтверждения работоспособности сессии.
    """
    cookie_row = await get_active_cookie(session)
    if cookie_row:
        cookie_row.health = health
        if health == "ok":
            cookie_row.last_verified_at = datetime.now()
        await session.commit()
