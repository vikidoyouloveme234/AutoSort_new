"""Google Sheets reader — читает листы через gspread (сервисный аккаунт)."""
import gspread

from app.config import settings

_client: gspread.Client | None = None


def get_client() -> gspread.Client:
    global _client
    if _client is None:
        _client = gspread.service_account(filename=settings.google_service_account_file)
    return _client


def get_sheet(worksheet_name: str) -> gspread.Worksheet:
    spreadsheet = get_client().open_by_key(settings.google_sheet_id)
    return spreadsheet.worksheet(worksheet_name)


def read_tasks_raw() -> list[list[str]]:
    """Возвращает все строки листа «Задания» (включая заголовок)."""
    return get_sheet("Задания").get_all_values()


def read_warehouses_raw() -> list[str]:
    """Возвращает список названий складов из листа «Склады»."""
    values = get_sheet("Склады").col_values(1)
    return [v.strip() for v in values if v.strip()]


def read_articles_raw() -> list[tuple[str, str]]:
    """Возвращает список (код, nmID) из листа «Артикулы»."""
    rows = get_sheet("Артикулы").get_all_values()
    return [(r[0].strip(), r[1].strip()) for r in rows if len(r) >= 2]
