"""Диагностика таблицы «Задания» — только чтение, ничего не пишем.

Показывает:
- сколько строк «Создан» (кандидаты в обработку)
- какие склады не распознаются
- строки без nmID
- строки с истёкшим дедлайном
- общую разбивку по статусам

Использование:
    py scripts/inspect_tasks.py
"""
import asyncio
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog, logging
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    processors=[structlog.dev.ConsoleRenderer()],
)

from app.db.session import AsyncSessionLocal
from app.sheets import reader, parser
from app.db.models.task import TaskStatus


async def main() -> None:
    print("\n=== Читаем таблицу «Задания» ===")
    raw_rows = reader.read_tasks_raw()
    data_rows = raw_rows[1:]  # без заголовка
    print(f"Всего строк данных: {len(data_rows)}")

    # Получаем список складов из БД
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        from app.db.models.warehouse import Warehouse
        result = await session.execute(select(Warehouse.canonical_name))
        known = set(result.scalars().all())
    print(f"Складов в БД: {len(known)}\n")

    tasks, skipped = parser.parse_tasks(data_rows, known)

    # --- Разбивка по статусам ---
    status_counts: Counter[str] = Counter(t.status for t in tasks)
    print("=== Статусы (распознанные строки) ===")
    for status, cnt in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {status or '(пусто)':<30} {cnt}")
    print(f"  {'ИТОГО':<30} {len(tasks)}")

    # --- Пропущенные строки ---
    skip_reasons: Counter[str] = Counter(s.reason for s in skipped)
    print(f"\n=== Пропущено строк: {len(skipped)} ===")
    for reason, cnt in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"  [{cnt:>4}] {reason}")

    # --- Кандидаты в обработку (Создан) ---
    today = date.today()
    candidates = [t for t in tasks if t.status == TaskStatus.CREATED]
    print(f"\n=== Статус «Создан»: {len(candidates)} строк ===")

    no_nm_id    = [t for t in candidates if not t.nm_id]
    expired     = [t for t in candidates if t.deadline and today > t.deadline]
    no_src_wh   = [t for t in candidates if t.warehouse_src not in known]
    no_dst_wh   = [t for t in candidates if t.warehouse_dst not in known]
    ready       = [
        t for t in candidates
        if t.nm_id
        and (not t.deadline or today <= t.deadline)
        and t.warehouse_src in known
        and t.warehouse_dst in known
    ]

    print(f"  Готовы к отправке          : {len(ready)}")
    print(f"  Нет nmID                   : {len(no_nm_id)}")
    print(f"  Дедлайн истёк              : {len(expired)}")
    print(f"  Склад отгрузки не в БД     : {len(no_src_wh)}")
    print(f"  Склад получения не в БД    : {len(no_dst_wh)}")

    if no_src_wh:
        bad_src = Counter(t.warehouse_src for t in no_src_wh)
        print(f"\n  Неизвестные склады отгрузки:")
        for name, cnt in bad_src.most_common():
            print(f"    [{cnt:>3}] «{name}»")

    if no_dst_wh:
        bad_dst = Counter(t.warehouse_dst for t in no_dst_wh)
        print(f"\n  Неизвестные склады получения:")
        for name, cnt in bad_dst.most_common():
            print(f"    [{cnt:>3}] «{name}»")

    if ready:
        print(f"\n  Первые 5 готовых к отправке:")
        for t in ready[:5]:
            print(f"    row={t.row_number} nmID={t.nm_id} {t.warehouse_src} → {t.warehouse_dst} qty={t.quantity}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
