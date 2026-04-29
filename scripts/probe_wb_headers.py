"""Зондирует rate-limit метаданные WB из response headers.

Делает 10 последовательных запросов к /stocks и /quota и печатает все
заголовки. Ищем стандартные X-RateLimit-Limit / Remaining / Reset /
Retry-After / X-Ratelimit-Retry — если WB их шлёт, можно настроить
наш лимитер по реальным цифрам, а не угадывать.
"""
import asyncio
import sys

import httpx

from app.db.session import AsyncSessionLocal
from app.services.cookie_service import get_decrypted_credentials
from app.wb_client._common import STATIC_HEADERS
from app.wb_client.auth import refresh_seller_lk

BASE = "https://seller-weekly-report.wildberries.ru/ns/shifts/analytics-back/api/v1"

# Какие заголовки специально подсвечивать
RATELIMIT_HEADER_PATTERNS = (
    "ratelimit", "rate-limit", "retry", "throttle", "quota", "limit",
)


def _print_relevant_headers(headers: httpx.Headers, label: str) -> None:
    matches = [
        (k, v) for k, v in headers.items()
        if any(p in k.lower() for p in RATELIMIT_HEADER_PATTERNS)
    ]
    if matches:
        print(f"  [{label}] RATE-LIMIT META:")
        for k, v in matches:
            print(f"    {k}: {v}")
    else:
        print(f"  [{label}] нет rate-limit заголовков")


async def main(nm_id: int, office_id: int) -> None:
    async with AsyncSessionLocal() as s:
        creds = await get_decrypted_credentials(s)
    if creds is None:
        print("Нет активных куки в БД — сначала залей через scripts/load_cookies.py")
        return
    cookie_str, authorizev3 = creds

    seller_lk = await refresh_seller_lk(cookie_str, authorizev3)
    if seller_lk is None:
        print("refresh_seller_lk вернул None — куки не работают")
        return

    headers = {
        **STATIC_HEADERS,
        "authorizev3": authorizev3,
        "wb-seller-lk": seller_lk,
        "Cookie": cookie_str,
    }

    async with httpx.AsyncClient() as client:
        # --- /stocks ---
        print("=" * 70)
        print(f"ПРОБА /stocks?nmID={nm_id} — 10 последовательных запросов")
        print("=" * 70)
        for i in range(1, 11):
            resp = await client.get(f"{BASE}/stocks?nmID={nm_id}",
                                    headers=headers, timeout=15)
            print(f"\n#{i} status={resp.status_code}")
            _print_relevant_headers(resp.headers, "stocks")
            if i == 1:
                print("  (полный набор headers первого ответа):")
                for k, v in resp.headers.items():
                    print(f"    {k}: {v}")

        # --- /quota ---
        print("\n" + "=" * 70)
        print(f"ПРОБА /quota?officeID={office_id}&type=dst — 5 запросов")
        print("=" * 70)
        for i in range(1, 6):
            resp = await client.get(
                f"{BASE}/quota?officeID={office_id}&type=dst",
                headers=headers, timeout=15,
            )
            print(f"\n#{i} status={resp.status_code}")
            _print_relevant_headers(resp.headers, "quota")


if __name__ == "__main__":
    nm = int(sys.argv[1]) if len(sys.argv) > 1 else 292195892
    office = int(sys.argv[2]) if len(sys.argv) > 2 else 507  # Коледино
    asyncio.run(main(nm, office))
