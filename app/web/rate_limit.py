"""Простой in-memory rate limiter для admin-эндпоинтов.

Защита от:
- bruteforce пароля на /login
- клик-спама на /run, /bot/toggle и т.д.

Хранит timestamps по ключу (IP-адрес). В single-worker развёртке этого
достаточно. Для multi-worker нужен был бы Redis, но у нас по архитектуре
уже один worker (см. CLAUDE.md про APScheduler).
"""
from collections import defaultdict, deque
from time import time

from fastapi import Request

# key → deque of timestamps
_buckets: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    """Ключ для rate-limit: IP-адрес клиента.

    За nginx используем X-Real-IP (nginx перезаписывает его реальным IP клиента
    перед проксированием — см. default.conf.template). НЕ используем X-Forwarded-For:
    его клиент может подделать, что дало бы обход rate-limit через смену значения.
    """
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


def check_rate_limit(
    request: Request,
    bucket: str,
    *,
    max_attempts: int,
    window_sec: int,
) -> bool:
    """Возвращает True если запрос в пределах лимита, False если превышен.

    bucket — название бакета (например, "login" или "action"); разные бакеты
    не мешают друг другу.
    """
    key = f"{bucket}:{_client_key(request)}"
    now = time()
    cutoff = now - window_sec
    q = _buckets[key]
    # Удаляем устаревшие timestamps
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= max_attempts:
        return False
    q.append(now)
    return True


def reset_all() -> None:
    """Сбросить все бакеты — используется в тестах."""
    _buckets.clear()
