"""Одноразовый тест реального submit в WB.

ВНИМАНИЕ: отправляет ПРОДАКШН-запрос к shifts/analytics-back.
Если WB примет — в ЛК появится реальная заявка на перераспределение.

Не использует .env для override — только в памяти процесса.
"""
import asyncio

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.services.cookie_service import get_decrypted_credentials
from app.wb_client.client import OrderRequest, submit_order


async def main() -> None:
    # Отключаем dry-run только для этого процесса, .env не трогаем
    settings.wb_dry_run = False

    async with AsyncSessionLocal() as session:
        creds = await get_decrypted_credentials(session)
    if creds is None:
        print("NO COOKIE in DB")
        return
    cookie_str, authorizev3 = creds

    order = OrderRequest(
        src_warehouse_id=130744,   # Краснодар
        dst_warehouse_id=208277,   # Невинномысск
        nm_id=445638987,
        chrt_id=630063287,         # размер 35
        count=5,
    )

    print(f"Отправка: nm={order.nm_id} chrt={order.chrt_id} "
          f"src={order.src_warehouse_id} dst={order.dst_warehouse_id} qty={order.count}")
    resp = await submit_order(order, cookie_str, authorizev3)

    print("-" * 60)
    print(f"success:     {resp.success}")
    print(f"status_code: {resp.status_code}")
    print(f"body:        {resp.body}")


if __name__ == "__main__":
    asyncio.run(main())
