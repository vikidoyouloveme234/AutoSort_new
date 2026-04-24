"""Удаляет все куки из БД (wb_cookies). Инвалидирует in-memory кэши."""
import asyncio

from sqlalchemy import delete, select

from app.db.models.cookie import WbCookie
from app.db.session import AsyncSessionLocal
from app.wb_client.auth import invalidate_token_cache


async def main() -> None:
    async with AsyncSessionLocal() as s:
        count_before = (await s.execute(select(WbCookie))).scalars().all()
        print(f"Было записей в wb_cookies: {len(count_before)}")

        await s.execute(delete(WbCookie))
        await s.commit()

        count_after = (await s.execute(select(WbCookie))).scalars().all()
        print(f"Стало: {len(count_after)}")

    invalidate_token_cache()
    print("wb-seller-lk cache сброшен")


if __name__ == "__main__":
    asyncio.run(main())
