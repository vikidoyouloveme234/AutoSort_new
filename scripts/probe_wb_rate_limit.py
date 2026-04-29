"""Probe-скрипт: ищет реальный rate-limit WB ЛК.

Шлёт /stocks?nmID=... с возрастающим темпом 1→2→3→...→N req/s.
Каждый уровень держит N секунд (по умолчанию 10). Останавливается
автоматически, если на текущем уровне ≥30% запросов вернули 429
(нет смысла идти выше). Не использует in-memory кэш — каждый запрос
бьёт WB напрямую.

ВАЖНО: запускать в безопасное время (НЕ во время midnight rush
00:00/09:00/18:00 МСК), желательно остановить APScheduler в админке
(«⏸ Остановить» в настройках), чтобы не конкурировать с нашим же ботом.
"""
import asyncio
import sys
import time
from collections import Counter

import httpx

from app.db.session import AsyncSessionLocal
from app.services.cookie_service import get_decrypted_credentials
from app.wb_client._common import STATIC_HEADERS
from app.wb_client.auth import refresh_seller_lk

URL_TEMPLATE = (
    "https://seller-weekly-report.wildberries.ru"
    "/ns/shifts/analytics-back/api/v1/stocks?nmID={nm_id}"
)

LEVEL_DURATION_SEC = 10        # сколько держим каждый уровень
MAX_RATE = 12                  # дальше нет смысла, и так понятно что упёрлись
STOP_THRESHOLD_429 = 0.3       # ≥30% 429 на уровне — стоп
COOLDOWN_BETWEEN_LEVELS_SEC = 5  # пауза перед следующим уровнем (даём WB остыть)


async def _one_request(client: httpx.AsyncClient, url: str, headers: dict) -> int:
    try:
        resp = await client.get(url, headers=headers, timeout=10)
        return resp.status_code
    except httpx.RequestError:
        return -1  # сетевая ошибка


async def _run_level(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    rate: int,
    duration: int,
) -> Counter:
    """Шлёт rate*duration запросов равномерно и собирает статусы."""
    total = rate * duration
    interval = 1.0 / rate
    tasks: list[asyncio.Task] = []

    start = time.monotonic()
    for i in range(total):
        target_time = start + i * interval
        sleep_for = target_time - time.monotonic()
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)
        tasks.append(asyncio.create_task(_one_request(client, url, headers)))

    statuses = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start
    counter = Counter(statuses)
    actual_rate = total / elapsed
    print(
        f"  rate={rate}/s ({total} req за {elapsed:.1f}s, актуально ~{actual_rate:.2f}/s)"
        f"  → {dict(counter)}"
    )
    return counter


async def main(nm_id: int) -> None:
    async with AsyncSessionLocal() as s:
        creds = await get_decrypted_credentials(s)
    if creds is None:
        print("Нет активных куки в БД")
        return
    cookie_str, authorizev3 = creds

    seller_lk = await refresh_seller_lk(cookie_str, authorizev3)
    if seller_lk is None:
        print("refresh_seller_lk вернул None")
        return

    headers = {
        **STATIC_HEADERS,
        "authorizev3": authorizev3,
        "wb-seller-lk": seller_lk,
        "Cookie": cookie_str,
    }
    url = URL_TEMPLATE.format(nm_id=nm_id)

    print(f"=== Probe rate-limit на /stocks?nmID={nm_id} ===")
    print(f"Уровни 1→{MAX_RATE} req/s, по {LEVEL_DURATION_SEC}s каждый, "
          f"стоп при ≥{int(STOP_THRESHOLD_429*100)}% 429")
    print()

    results: dict[int, Counter] = {}
    async with httpx.AsyncClient() as client:
        for rate in range(1, MAX_RATE + 1):
            counter = await _run_level(client, url, headers, rate, LEVEL_DURATION_SEC)
            results[rate] = counter

            total = sum(counter.values())
            ratio_429 = counter.get(429, 0) / total if total else 0

            if ratio_429 >= STOP_THRESHOLD_429:
                print(f"\n⚠️  На rate={rate}/s доля 429 = {ratio_429:.0%} ≥ "
                      f"{STOP_THRESHOLD_429:.0%} — останавливаемся.")
                break

            # Дать WB остыть перед следующим уровнем
            if rate < MAX_RATE:
                await asyncio.sleep(COOLDOWN_BETWEEN_LEVELS_SEC)

    print("\n=== ИТОГ ===")
    for rate, counter in results.items():
        total = sum(counter.values())
        success = counter.get(200, 0)
        rate_429 = counter.get(429, 0)
        rate_other = total - success - rate_429
        print(f"  {rate}/s: успехов={success}, 429={rate_429}, прочее={rate_other}")

    # Найти максимум, на котором НЕ было 429
    safe_rates = [r for r, c in results.items() if c.get(429, 0) == 0]
    if safe_rates:
        print(f"\n✅ Максимальный темп без единого 429: {max(safe_rates)} req/s")
    first_429 = next((r for r, c in results.items() if c.get(429, 0) > 0), None)
    if first_429:
        print(f"⚠️  Первое появление 429 на rate={first_429} req/s")


if __name__ == "__main__":
    nm = int(sys.argv[1]) if len(sys.argv) > 1 else 983506764
    asyncio.run(main(nm))
