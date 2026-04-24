"""Одноразовый скрипт: показывает остатки по nmID со всеми chrtID (размерами)."""
import asyncio
import json
import sys

import httpx

from app.db.session import AsyncSessionLocal
from app.services.cookie_service import get_decrypted_credentials
from app.wb_client._common import STATIC_HEADERS
from app.wb_client.auth import refresh_seller_lk

URL = "https://seller-weekly-report.wildberries.ru/ns/shifts/analytics-back/api/v1/stocks"


async def main(nm_id: int) -> None:
    async with AsyncSessionLocal() as session:
        creds = await get_decrypted_credentials(session)
    if creds is None:
        print("НЕТ активных куки в БД")
        return
    cookie_str, authorizev3 = creds

    seller_lk = await refresh_seller_lk(cookie_str, authorizev3)
    if seller_lk is None:
        print("refresh_seller_lk вернул None — куки не работают (либо схема auth поменялась)")
        return

    headers = {
        **STATIC_HEADERS,
        "authorizev3": authorizev3,
        "wb-seller-lk": seller_lk,
        "Cookie": cookie_str,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{URL}?nmID={nm_id}", headers=headers, timeout=15)

    print(f"HTTP {resp.status_code}")
    if not resp.is_success:
        print(resp.text[:500])
        return
    body = resp.json()
    if body.get("error"):
        print("ERROR:", body.get("errorText"))
        return

    print(json.dumps(body, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    nm = int(sys.argv[1]) if len(sys.argv) > 1 else 292195892
    asyncio.run(main(nm))
