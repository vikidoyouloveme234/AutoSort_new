"""Разведка GET-endpoint'ов ЛК WB через куки (без Персонального токена).

Найдено реверсом 2026-04-18 — полный workflow создания заявки на перераспределение.
"""
import asyncio
import json
import httpx

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.services.cookie_service import get_decrypted_credentials
from app.wb_client.auth import refresh_seller_lk
from app.wb_client.client import _STATIC_HEADERS

BASE = "https://seller-weekly-report.wildberries.ru/ns/shifts/analytics-back/api/v1"

NM_ID = 443589786
SRC = 130744   # Краснодар
DST = 208277   # Невинномысск


async def call(client, url, headers, label):
    print(f"\n{'=' * 70}\n  {label}\n  {url}\n{'=' * 70}")
    try:
        r = await client.get(url, headers=headers, timeout=15)
    except Exception as e:
        print(f"  ERROR: {e}")
        return
    print(f"  status: {r.status_code}")
    try:
        body = r.json()
        print(f"  body:")
        print(json.dumps(body, ensure_ascii=False, indent=4)[:2000])
    except Exception:
        print(f"  raw: {r.text[:500]}")


async def main():
    settings.wb_dry_run = False

    async with AsyncSessionLocal() as session:
        creds = await get_decrypted_credentials(session)
    if creds is None:
        print("NO COOKIE")
        return
    cookie_str, authorizev3 = creds
    seller_lk = await refresh_seller_lk(cookie_str, authorizev3)
    if seller_lk is None:
        print("token_refresh_failed")
        return

    headers = {
        **_STATIC_HEADERS,
        "authorizev3": authorizev3,
        "wb-seller-lk": seller_lk,
        "Cookie": cookie_str,
    }

    async with httpx.AsyncClient() as client:
        await call(client, f"{BASE}/nms?pattern={NM_ID}", headers, "1) /nms — поиск товара")
        await call(client, f"{BASE}/stocks?nmID={NM_ID}", headers, "2) /stocks — остатки")
        await call(client, f"{BASE}/quota?officeID={SRC}&type=src", headers, "3) /quota src")
        await call(client, f"{BASE}/quota?officeID={DST}&type=dst", headers, "4) /quota dst")


if __name__ == "__main__":
    asyncio.run(main())
