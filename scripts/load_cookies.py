"""Одноразовый: грузит куки из JSON-дампа Cookie-Editor в БД."""
import asyncio
import json
import sys
from pathlib import Path

from app.db.session import AsyncSessionLocal
from app.services.cookie_service import save_cookie


async def main(json_path: str, authorizev3: str) -> None:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in data)

    async with AsyncSessionLocal() as session:
        row = await save_cookie(
            session,
            cookie_str=cookie_str,
            headers={"authorizev3": authorizev3} if authorizev3 else None,
        )
    print(f"saved id={row.id}, is_active={row.is_active}")
    print(f"cookie_str length={len(cookie_str)}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "wb_cookie.txt"
    auth = sys.argv[2] if len(sys.argv) > 2 else ""
    asyncio.run(main(path, auth))
