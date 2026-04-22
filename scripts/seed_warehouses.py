"""Seed-скрипт — заполняет таблицу warehouses подтверждёнными данными.

Источник: WB FBW API + подтверждение заказчика 2026-04-16.
wb_warehouse_id — из supplies-api.wildberries.ru/api/v1/warehouses.
ВНИМАНИЕ: эти ID могут не совпадать с ID в shifts/analytics-back —
нужна верификация после получения cURL от заказчика.

Запуск (после alembic upgrade head):
    py scripts/seed_warehouses.py
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DATABASE_URL = os.environ["DATABASE_URL"]

# canonical_name  — название из листа «Склады» (именно так пишет заказчик)
# wb_warehouse_id — ID из WB FBW API (supplies-api)
# aliases         — через запятую; то, что пишут в «Задания» вместо полного имени
WAREHOUSES = [
    # name                              wb_id       aliases
    ("Коледино",                        507,        ""),
    ("Электросталь",                    120762,     ""),
    ("Склад Шушары",                    50045246,   "СПБ"),           # подтверждено заказчиком
    ("Краснодар",                       130744,     ""),              # WB name: Краснодар (Тихорецкая)
    ("Екатеринбург - Перспективная 14", 300571,     "Екатеринбург"), # подтверждено заказчиком
    ("Тула",                            206348,     ""),
    ("Невинномысск",                    208277,     ""),
    ("Рязань (Тюшевское)",              301760,     ""),
    ("Котовск",                         301809,     ""),
    ("Самара (Новосемейкино)",          301805,     ""),              # WB name: Новосемейкино
    ("Казань",                          117986,     ""),
    ("Волгоград",                       301983,     ""),
    ("Владимир",                        301981,     ""),              # WB name: Владимир Воршинское
    ("Сарапул",                         301987,     ""),
    ("Пенза",                           50045809,   ""),
    ("Новосибирск",                     686,        ""),
]


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        for canonical_name, wb_id, aliases in WAREHOUSES:
            await session.execute(
                text("""
                    INSERT INTO warehouses (canonical_name, wb_warehouse_id, aliases)
                    VALUES (:name, :wb_id, :aliases)
                    ON CONFLICT (canonical_name) DO UPDATE
                        SET wb_warehouse_id = EXCLUDED.wb_warehouse_id,
                            aliases         = EXCLUDED.aliases
                """),
                {"name": canonical_name, "wb_id": wb_id, "aliases": aliases or None},
            )
        await session.commit()

    await engine.dispose()
    print(f"Done: {len(WAREHOUSES)} warehouses seeded.")


if __name__ == "__main__":
    asyncio.run(main())
