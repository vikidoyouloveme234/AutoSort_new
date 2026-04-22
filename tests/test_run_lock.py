"""Тесты глобального run-lock'а."""
from app.services.run_lock import _reset_for_tests, is_running, release, try_acquire


def setup_function() -> None:
    _reset_for_tests()


def test_initial_state_not_running() -> None:
    assert is_running() is False


def test_try_acquire_first_call_succeeds() -> None:
    assert try_acquire() is True
    assert is_running() is True


def test_try_acquire_second_call_fails() -> None:
    assert try_acquire() is True
    assert try_acquire() is False
    # Сохраняет состояние занятости
    assert is_running() is True


def test_release_allows_next_acquire() -> None:
    try_acquire()
    release()
    assert is_running() is False
    assert try_acquire() is True  # снова можно


def test_release_when_not_held_is_idempotent() -> None:
    """release() на незанятом lock — не должен падать."""
    release()
    assert is_running() is False
