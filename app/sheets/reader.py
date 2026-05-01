"""Google Sheets reader — читает листы через gspread (сервисный аккаунт).

Кэширует worksheet-объекты на уровне модуля чтобы каждый вызов не делал
лишних API-запросов на open_by_key/worksheet — gspread их не кэширует сам.
Каждый вызов к данным (get_all_values/col_values) идёт через rate-limiter.
"""
import gspread

from app.config import settings
from app.sheets import _rate_limit

_client: gspread.Client | None = None
_worksheets: dict[str, gspread.Worksheet] = {}


def get_client() -> gspread.Client:
    global _client
    if _client is None:
        _client = gspread.service_account(filename=settings.google_service_account_file)
    return _client


def get_sheet(worksheet_name: str) -> gspread.Worksheet:
    """Возвращает worksheet, кэшируя по имени.

    Первый вызов делает 2 API-запроса (open_by_key + worksheet) — учитываем
    в rate-limiter. Последующие вызовы — из локального кэша, бесплатные.
    """
    cached = _worksheets.get(worksheet_name)
    if cached is not None:
        return cached
    _rate_limit.acquire()  # open_by_key
    spreadsheet = get_client().open_by_key(settings.google_sheet_id)
    _rate_limit.acquire()  # worksheet (gspread может или не делать сетевой вызов — учитываем на всякий)
    ws = spreadsheet.worksheet(worksheet_name)
    _worksheets[worksheet_name] = ws
    return ws


def read_tasks_raw() -> list[list[str]]:
    """Возвращает все строки листа «Задания» (включая заголовок)."""
    ws = get_sheet("Задания")
    _rate_limit.acquire()
    return ws.get_all_values()


def read_warehouses_raw() -> list[str]:
    """Возвращает список названий складов из листа «Склады»."""
    ws = get_sheet("Склады")
    _rate_limit.acquire()
    values = ws.col_values(1)
    return [v.strip() for v in values if v.strip()]


def read_articles_raw() -> list[tuple[str, str]]:
    """Возвращает список (код, nmID) из листа «Артикулы»."""
    ws = get_sheet("Артикулы")
    _rate_limit.acquire()
    rows = ws.get_all_values()
    return [(r[0].strip(), r[1].strip()) for r in rows if len(r) >= 2]
