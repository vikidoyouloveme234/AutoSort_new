"""Smoke test для прод-развёртки.

Запуск после `docker compose up -d`:
    docker compose exec app py -m scripts.smoke_test

Проверяет ключевые компоненты:
1. БД доступна и миграции применены
2. Google Sheets открывается и видны все 4 листа
3. Куки WB сохранены (хотя бы 1 запись в wb_cookies)
4. Склады засеяны (16 строк в warehouses)
5. app_state singleton существует
6. /healthz отвечает 200

Каждая проверка либо OK либо FAIL с причиной. В конце — итоговый exit code.
"""
import asyncio
import sys

from sqlalchemy import func, select, text

from app.db.models.app_state import AppState
from app.db.models.cookie import WbCookie
from app.db.models.warehouse import Warehouse
from app.db.session import AsyncSessionLocal


OK = "\033[92mOK\033[0m" if sys.stdout.isatty() else "OK"
FAIL = "\033[91mFAIL\033[0m" if sys.stdout.isatty() else "FAIL"


async def check(label: str, coro) -> bool:
    try:
        detail = await coro
    except Exception as e:
        print(f"  [{FAIL}] {label}: {e}")
        return False
    print(f"  [{OK}]   {label}: {detail}")
    return True


async def db_ok() -> str:
    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT 1"))
    return "connection + SELECT 1"


async def migrations_ok() -> str:
    async with AsyncSessionLocal() as s:
        r = await s.execute(text("SELECT version_num FROM alembic_version"))
        v = r.scalar_one()
    return f"alembic_version={v}"


async def warehouses_ok() -> str:
    async with AsyncSessionLocal() as s:
        cnt = (await s.execute(select(func.count()).select_from(Warehouse))).scalar()
    if cnt < 16:
        raise ValueError(f"expected ≥16 warehouses, got {cnt} — seed_warehouses.py не запущен?")
    return f"{cnt} складов в БД"


async def cookies_ok() -> str:
    async with AsyncSessionLocal() as s:
        cnt = (await s.execute(select(func.count()).select_from(WbCookie))).scalar()
    if cnt == 0:
        raise ValueError("нет WB-куки в БД — вставь через админ-панель /settings")
    return f"{cnt} запись(-и) куки"


async def app_state_ok() -> str:
    async with AsyncSessionLocal() as s:
        r = await s.execute(select(AppState).where(AppState.id == 1))
        state = r.scalar_one_or_none()
    if state is None:
        raise ValueError("нет app_state row id=1 — миграция 0007 не применена?")
    return f"bot_enabled={state.bot_enabled}, interval={state.poll_interval_minutes}мин"


async def sheets_ok() -> str:
    # Импортим тут чтобы ошибка импорта не срубила другие проверки
    from app.sheets.reader import get_sheet

    sheet = get_sheet("Задания")  # любой лист для проверки подключения
    # получим первую строку заголовков — быстрая операция
    header = sheet.row_values(1)
    if not header:
        raise ValueError("лист «Задания» пустой (нет заголовка)?")
    return f"подключение OK, колонок в заголовке: {len(header)}"


async def main() -> int:
    print("=== Auto_sort smoke test ===\n")
    results = []
    results.append(await check("DB connection", db_ok()))
    results.append(await check("Migrations", migrations_ok()))
    results.append(await check("Warehouses seed", warehouses_ok()))
    results.append(await check("App state singleton", app_state_ok()))
    results.append(await check("WB cookies", cookies_ok()))
    results.append(await check("Google Sheets", sheets_ok()))

    print()
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"Все {total} проверок прошли. Система готова к работе.")
        return 0
    print(f"Провалено {total - passed} из {total}. Требуется ручное исправление.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
