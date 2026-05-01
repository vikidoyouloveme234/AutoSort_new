"""Запись статусов обратно в Google Sheets.

Бот пишет только в колонки: H (Статус), I (Дата выполнения), L (Требует реакции), M (Коментарий).
Колонки A–G, J, K — не трогаем никогда.
"""
from datetime import date

import gspread
import structlog

from app.sheets import _rate_limit
from app.sheets.reader import get_sheet

log = structlog.get_logger()

# Индексы колонок (1-based, как в gspread)
COL_STATUS = 8          # H
COL_DATE_DONE = 9       # I
COL_NEEDS_ATTENTION = 12  # L
COL_COMMENT = 13        # M


def _fmt_date(d: date | None) -> str:
    return d.strftime("%d.%m.%y") if d else ""


def update_task_row(
    row: int,
    *,
    status: str | None = None,
    date_done: date | None = None,
    needs_attention: bool | None = None,
    comment: str | None = None,
) -> None:
    """Обновляет одну строку листа «Задания».

    Передавай только те поля, которые нужно изменить.
    row — 1-based номер строки в таблице (строка 1 = заголовок).
    """
    ws = get_sheet("Задания")
    updates: list[tuple[int, int, str]] = []  # (row, col, value)

    if status is not None:
        updates.append((row, COL_STATUS, status))
    if date_done is not None:
        updates.append((row, COL_DATE_DONE, _fmt_date(date_done)))
    if needs_attention is not None:
        updates.append((row, COL_NEEDS_ATTENTION, "Да" if needs_attention else ""))
    if comment is not None:
        updates.append((row, COL_COMMENT, comment))

    if not updates:
        return

    # Батчим все изменения в один запрос к Sheets API.
    # RAW — защита от инъекции формул: комментарий вида "=HYPERLINK(...)" не исполнится.
    cell_list = [
        gspread.Cell(row=r, col=c, value=v)
        for r, c, v in updates
    ]
    _rate_limit.acquire()
    ws.update_cells(cell_list, value_input_option="RAW")
    log.info("sheet_row_updated", row=row, fields=[c for _, c, _ in updates])


def mark_skipped(row: int, reason: str) -> None:
    """Ставит флаг «Требует реакции» и пишет причину в Коментарий."""
    update_task_row(row, needs_attention=True, comment=reason)
