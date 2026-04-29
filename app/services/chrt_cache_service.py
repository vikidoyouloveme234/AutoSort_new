"""Get/upsert chrt_id в БД-кэше (fallback для failed /stocks)."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chrt_cache import ChrtCache


async def get_cached_chrt_id(session: AsyncSession, nm_id: int) -> int | None:
    row = await session.get(ChrtCache, nm_id)
    return row.chrt_id if row else None


async def upsert_chrt_cache(session: AsyncSession, nm_id: int, chrt_id: int) -> None:
    """Создаёт или обновляет запись, коммитит сразу.

    Коммит здесь (а не у caller'а) принципиален: chrt_id апсертится в
    task_processor до submit, и нам важно не потерять его, даже если
    все последующие submit'ы упадут по квоте. Без commit'а на месте
    ChrtCache остался бы пустым весь цикл, и cache-first путь не работал
    бы при следующих повторных попытках.
    """
    row = await session.get(ChrtCache, nm_id)
    if row is None:
        session.add(ChrtCache(nm_id=nm_id, chrt_id=chrt_id))
    elif row.chrt_id == chrt_id:
        return  # ничего не менялось — не коммитим зря
    else:
        row.chrt_id = chrt_id
    await session.commit()
