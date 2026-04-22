"""Cookie-based аутентификация + CSRF для админ-панели.

Сессия: httponly cookie `as_session` = SHA-256(session_version + secret_key).
`session_version` живёт в app_state и может быть инкрементирован, что revoke'ит
ВСЕ выпущенные cookies разом (кнопка «Сбросить все сессии» в админке).

CSRF: отдельный httponly cookie `as_csrf` со случайным токеном (double-submit).
"""
import hashlib
import secrets

from fastapi import Request
from fastapi.responses import Response

from app.config import settings
from app.constants import SESSION_COOKIE_MAX_AGE_SEC

_COOKIE_NAME = "as_session"
_CSRF_COOKIE = "as_csrf"

# Текущая версия выпуска сессий. Читается на старте из app_state.session_version.
# При bump'е — все выпущенные cookies с предыдущей версией становятся невалидными.
_current_session_version: int = 1


def set_current_session_version(version: int) -> None:
    """Устанавливает версию сессий (вызывается при старте приложения и при bump'е).

    Все cookies с хэшем от СТАРОЙ версии перестают проходить is_authenticated.
    """
    global _current_session_version
    _current_session_version = version


def _make_token() -> str:
    """Хэш пароля + версии сессий. Меняется при bump → старые cookies инвалидны."""
    return hashlib.sha256(
        f"admin:{_current_session_version}:{settings.admin_secret_key}".encode()
    ).hexdigest()


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(_COOKIE_NAME, "")
    if not token:
        return False
    return secrets.compare_digest(token, _make_token())


def set_session(response: Response, *, authenticated: bool) -> None:
    if authenticated:
        response.set_cookie(
            _COOKIE_NAME,
            _make_token(),
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
            max_age=SESSION_COOKIE_MAX_AGE_SEC,
        )
    else:
        response.delete_cookie(_COOKIE_NAME)
        response.delete_cookie(_CSRF_COOKIE)


def get_csrf_token(request: Request) -> tuple[str, bool]:
    existing = request.cookies.get(_CSRF_COOKIE, "")
    if existing:
        return existing, False
    return secrets.token_urlsafe(32), True


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        _CSRF_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=settings.session_cookie_secure,
        max_age=SESSION_COOKIE_MAX_AGE_SEC,
    )


def verify_csrf(request: Request, form_token: str) -> bool:
    cookie_token = request.cookies.get(_CSRF_COOKIE, "")
    if not cookie_token or not form_token:
        return False
    return secrets.compare_digest(cookie_token, form_token)
