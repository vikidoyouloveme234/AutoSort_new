"""Smoke-test: проверяет upsert + get ChrtCache через реальную БД."""
import asyncio

from app.db.models.chrt_cache import ChrtCache
from app.db.session import AsyncSessionLocal
from app.services.chrt_cache_service import get_cached_chrt_id, upsert_chrt_cache
from sqlalchemy import delete


async def main() -> None:
    async with AsyncSessionLocal() as s:
        # Cleanup
        await s.execute(delete(ChrtCache).where(ChrtCache.nm_id == 999999999))
        await s.commit()

        # 1. miss
        assert await get_cached_chrt_id(s, 999999999) is None
        print("miss OK")

        # 2. insert
        await upsert_chrt_cache(s, 999999999, 111)
        got = await get_cached_chrt_id(s, 999999999)
        assert got == 111, f"expected 111, got {got}"
        print("insert OK")

        # 3. same value — idempotent
        await upsert_chrt_cache(s, 999999999, 111)
        assert await get_cached_chrt_id(s, 999999999) == 111
        print("idempotent OK")

        # 4. update
        await upsert_chrt_cache(s, 999999999, 222)
        got = await get_cached_chrt_id(s, 999999999)
        assert got == 222, f"expected 222, got {got}"
        print("update OK")

        # Cleanup
        await s.execute(delete(ChrtCache).where(ChrtCache.nm_id == 999999999))
        await s.commit()
        print("ALL PASSED")


if __name__ == "__main__":
    asyncio.run(main())
