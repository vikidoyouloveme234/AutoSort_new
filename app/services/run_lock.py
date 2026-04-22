"""Глобальный флаг «идёт process_once» — защита от concurrent запусков.

В asyncio-single-thread reading/setting bool атомарно (нет yield points между
чтением и записью). Это гарантирует что только одна корутина видит False и
успевает поставить True до того как другая проверит.

Используется везде где вызывается process_once:
- jobs.poll_tasks (scheduler + slot_rush)
- router._run_process_once (ручной запуск из UI)

Замена asyncio.Lock, у которого TOCTOU между .locked() и acquire() на последующем
await не даёт надёжно сказать «skip если занят».
"""
_is_running: bool = False


def try_acquire() -> bool:
    """Пытается забрать флаг. True — захватил (можно работать). False — уже занят."""
    global _is_running
    if _is_running:
        return False
    _is_running = True
    return True


def release() -> None:
    global _is_running
    _is_running = False


def is_running() -> bool:
    return _is_running


def _reset_for_tests() -> None:
    """Только для тестов."""
    global _is_running
    _is_running = False
