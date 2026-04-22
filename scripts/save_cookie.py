"""Одноразовый скрипт — шифрует и сохраняет WB-куки в БД.

Запускать после `make upgrade` (таблицы должны существовать).

Запуск:
    py scripts/save_cookie.py

Скрипт спросит интерактивно: куки и два JWT-токена.
Ничего не логируется и не пишется в файл — только в БД под Fernet.
"""
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main() -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.cookie_service import save_cookie

    print("=== Сохранение WB-куков в БД ===")
    print("Вставляй значения без кавычек. Ввод скрыт.\n")

    cookie_str = getpass.getpass("Cookie (полная строка из DevTools): ").strip()
    if not cookie_str:
        sys.exit("Пустые куки — отмена.")

    authorizev3 = getpass.getpass("authorizev3 (JWT): ").strip()
    # wb-seller-lk не храним — он короткоживущий (5 мин), получаем свежий перед каждым запросом

    headers: dict[str, str] = {}
    if authorizev3:
        headers["authorizev3"] = authorizev3

    async with AsyncSessionLocal() as session:
        row = await save_cookie(session, cookie_str, headers or None)

    print(f"\nГотово. Cookie ID={row.id}, health={row.health}")
    print("Теперь можно запускать бота.")


if __name__ == "__main__":
    asyncio.run(main())
