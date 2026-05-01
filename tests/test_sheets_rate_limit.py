"""Тесты Sheets rate limiter."""
import time

from app.sheets._rate_limit import SheetsRateLimiter


def test_no_throttle_under_limit() -> None:
    """3 вызова при лимите 5 — не должно быть задержки."""
    rl = SheetsRateLimiter(max_calls=5, period_sec=60)
    start = time.monotonic()
    for _ in range(3):
        rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"под лимитом не должно блокировать, потратили {elapsed}s"


def test_throttle_when_limit_hit() -> None:
    """4-й вызов при лимите 3 в окне 0.5s должен заблокироваться примерно на 0.5s."""
    rl = SheetsRateLimiter(max_calls=3, period_sec=1)  # period 1 sec для скорости теста
    rl._period = 0.5  # переопределяем для теста — 0.5s окно
    start = time.monotonic()
    for _ in range(4):
        rl.acquire()
    elapsed = time.monotonic() - start
    # 4-й должен подождать пока 1-й вылетит из окна (~0.5s)
    assert 0.3 < elapsed < 0.8, f"должен ждать ~0.5s, фактически {elapsed}s"


def test_window_slides() -> None:
    """После окна — лимит сбрасывается, можем снова делать N вызовов без задержки."""
    rl = SheetsRateLimiter(max_calls=2, period_sec=1)
    rl._period = 0.3
    rl.acquire()
    rl.acquire()
    time.sleep(0.4)  # ждём пока окно сдвинется
    start = time.monotonic()
    rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, f"после окна не должно блокировать, {elapsed}s"


def test_calls_recorded_in_deque() -> None:
    """После N вызовов в deque ровно N отметок (или меньше если устарели)."""
    rl = SheetsRateLimiter(max_calls=10, period_sec=60)
    for _ in range(5):
        rl.acquire()
    assert len(rl._calls) == 5
