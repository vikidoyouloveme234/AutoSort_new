"""Тестовый dry-run: получает chrtID для nmID и симулирует заявку на перераспределение.

Использование:
    python scripts/test_dry_run.py <nmID> [src_warehouse_id] [dst_warehouse_id]

По умолчанию src=130744 (Краснодар), dst=208277 (Невинномысск) — из живого cURL.
WB_DRY_RUN=true — реальный запрос не отправляется.
"""
import asyncio
import sys
from pathlib import Path

# Чтобы import app.* работал без установки пакета
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
import logging

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    processors=[
        structlog.dev.ConsoleRenderer(),
    ],
)

from app.db.session import AsyncSessionLocal
from app.services.cookie_service import get_decrypted_credentials
from app.wb_client.client import OrderRequest, submit_order
from app.wb_client.lk_stocks import fetch_stocks_lk


async def main(nm_id: int, src_wh: int, dst_wh: int) -> None:
    print(f"\n=== Dry-run тест: nmID={nm_id}, src={src_wh}, dst={dst_wh} ===\n")

    async with AsyncSessionLocal() as session:
        # 1. Получаем credentials
        creds = await get_decrypted_credentials(session)
        if creds is None:
            print("[ОШИБКА] Нет активного куки в БД. Запусти: python scripts/save_cookie.py")
            return
        cookie_str, authorizev3 = creds
        print(f"[OK] Credentials получены из БД (cookie len={len(cookie_str)}, authorizev3 len={len(authorizev3)})")

        # 2. Получаем chrtID через LK /stocks (был Content API, переехали 2026-04-18)
        print(f"\n[...] Запрашиваем chrtID для nmID={nm_id} через LK /stocks...")
        stocks = await fetch_stocks_lk(nm_id, cookie_str, authorizev3)
        if not stocks:
            print(f"[ОШИБКА] Товар nmID={nm_id} не найден ни на одном складе")
            print("  Проверь куки и что nmID принадлежит кабинету этих кук")
            return
        chrt_id = next(iter(stocks.values())).chrt_id
        print(f"[OK] chrtID={chrt_id}, найден на {len(stocks)} складах")

        # 3. Dry-run заявки
        order = OrderRequest(
            src_warehouse_id=src_wh,
            dst_warehouse_id=dst_wh,
            nm_id=nm_id,
            chrt_id=chrt_id,
            count=1,
        )
        print(f"\n[...] Отправляем dry-run заявку...")
        resp = await submit_order(order, cookie_str, authorizev3)
        print(f"\n=== Результат ===")
        print(f"  success     : {resp.success}")
        print(f"  status_code : {resp.status_code}")
        print(f"  body        : {resp.body}")

        if resp.success:
            print("\n[OK] Dry-run прошёл успешно — реальный запрос не отправлялся.")
        else:
            print("\n[ОШИБКА] Dry-run завершился неуспешно.")


if __name__ == "__main__":
    nm_id = int(sys.argv[1]) if len(sys.argv) > 1 else 292197811
    src_wh = int(sys.argv[2]) if len(sys.argv) > 2 else 130744   # Краснодар
    dst_wh = int(sys.argv[3]) if len(sys.argv) > 3 else 208277   # Невинномысск
    asyncio.run(main(nm_id, src_wh, dst_wh))
