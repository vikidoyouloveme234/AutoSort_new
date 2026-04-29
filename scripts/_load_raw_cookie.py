"""Загружает куки из переменных окружения WB_COOKIE / WB_AUTHORIZEV3."""
import asyncio
import os

from app.db.session import AsyncSessionLocal
from app.services.cookie_service import save_cookie


async def main() -> None:
    cookie_str = os.environ["WB_COOKIE"]
    authorizev3 = os.environ["WB_AUTHORIZEV3"]
    async with AsyncSessionLocal() as s:
        row = await save_cookie(s, cookie_str, headers={"authorizev3": authorizev3})
    print(f"saved id={row.id}, is_active={row.is_active}, len={len(cookie_str)}")


if __name__ == "__main__":
    asyncio.run(main())
