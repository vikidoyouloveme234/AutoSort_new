"""Очистка кабинетных данных перед передачей заказчику.

Удаляет:
- wb_cookies (зашифрованные куки твоего тестового кабинета)
- task_deliveries (трек-записи о заявках, которые сабмитил бот в твой кабинет)

НЕ удаляет:
- warehouses (справочник складов — общий, не кабинетный)
- alembic_version (история миграций)
- twkзе (вообще нет такой таблицы)

Использование:
    py -m scripts.reset_for_handover

Заказчик после деплоя сам:
- вставит свои куки через админ-панель
- увидит свежий task_deliveries (создаются при первой обработке)
"""
import asyncio

from sqlalchemy import delete, select, func
from app.db.session import AsyncSessionLocal
from app.db.models.cookie import WbCookie
from app.db.models.delivery import TaskDelivery
from app.db.models.warehouse import Warehouse


async def main() -> None:
    async with AsyncSessionLocal() as session:
        # До удаления — показать что есть
        wh_cnt = (await session.execute(select(func.count()).select_from(Warehouse))).scalar()
        ck_cnt = (await session.execute(select(func.count()).select_from(WbCookie))).scalar()
        td_cnt = (await session.execute(select(func.count()).select_from(TaskDelivery))).scalar()
        print(f"До очистки: warehouses={wh_cnt}, wb_cookies={ck_cnt}, task_deliveries={td_cnt}")

        # Удаляем
        c1 = await session.execute(delete(WbCookie))
        c2 = await session.execute(delete(TaskDelivery))
        await session.commit()

        print(f"Удалено: wb_cookies={c1.rowcount}, task_deliveries={c2.rowcount}")
        print(f"Сохранено: warehouses={wh_cnt} (справочник, нужен для работы)")
        print()
        print("Готово. Можешь отдавать репо заказчику.")
        print("Заказчик после деплоя:")
        print("  1. cp .env.example .env -> заполнить своими значениями")
        print("  2. Положить secrets/google_sa.json")
        print("  3. docker compose up -d")
        print("  4. Открыть админку → вставить свои куки WB")


if __name__ == "__main__":
    asyncio.run(main())
