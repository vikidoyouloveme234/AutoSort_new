"""Google Sheets reader — читает листы через gspread (сервисный аккаунт).

- Кэширует worksheet-объекты на уровне модуля (избегаем повторных
  open_by_key/worksheet вызовов).
- Каждый data-вызов проходит через `acquire_read()` лимитер (60/min)
  и `with_retry()` (4 попытки, exponential backoff на 429/5xx).
"""
import gspread

from app.config import settings
from app.sheets._rate_limit import acquire_read, with_retry

_client: gspread.Client | None = None
_worksheets: dict[str, gspread.Worksheet] = {}


def get_client() -> gspread.Client:
    global _client
    if _client is None:
        _client = gspread.service_account(filename=settings.google_service_account_file)
    return _client


def get_sheet(worksheet_name: str) -> gspread.Worksheet:
    """Возвращает worksheet, кэшируя по имени.

    Первый вызов — 1-2 API-запроса (open_by_key + worksheet), последующие —
    из локального кэша без сети.
    """
    cached = _worksheets.get(worksheet_name)
    if cached is not None:
        return cached
    acquire_read()
    spreadsheet = with_retry(
        "open_spreadsheet",
        lambda: get_client().open_by_key(settings.google_sheet_id),
    )
    acquire_read()
    ws = with_retry(
        f"open_worksheet:{worksheet_name}",
        lambda: spreadsheet.worksheet(worksheet_name),
    )
    _worksheets[worksheet_name] = ws
    return ws


def read_tasks_raw() -> list[list[str]]:
    """Возвращает все строки листа «Задания» (включая заголовок)."""
    ws = get_sheet("Задания")
    acquire_read()
    return with_retry("read_tasks", lambda: ws.get_all_values())


def read_warehouses_raw() -> list[str]:
    """Возвращает список названий складов из листа «Склады»."""
    ws = get_sheet("Склады")
    acquire_read()
    values = with_retry("read_warehouses", lambda: ws.col_values(1))
    return [v.strip() for v in values if v.strip()]


def read_articles_raw() -> list[tuple[str, str]]:
    """Возвращает список (код, nmID) из листа «Артикулы»."""
    ws = get_sheet("Артикулы")
    acquire_read()
    rows = with_retry("read_articles", lambda: ws.get_all_values())
    return [(r[0].strip(), r[1].strip()) for r in rows if len(r) >= 2]
