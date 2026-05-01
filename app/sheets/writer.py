"""Запись статусов обратно в Google Sheets с батчингом.

Бот пишет только в колонки: H (Статус), I (Дата выполнения), L (Требует
реакции), M (Коментарий). Колонки A–G, J, K — не трогаем никогда.

**Батчинг:** `update_task_row` копит ячейки в module-level буфере. Реальный
API-вызов к Sheets делается когда:
- Буфер набрал N разных строк (`SHEETS_WRITE_BATCH_ROWS = 10`)
- Явный вызов `flush()` (например в конце `process_once`)

Это даёт **10x+ throughput**: при 600 ячеек за цикл — ~30-60 API-вызовов
вместо 600. Customer'овская «визуальная индикация» сохраняется: маркер
«В очереди бота» появляется через ~5-10 сек после старта обработки строки
(время заполнения батча).

Если две записи в один цикл целятся в одну (row, col) — побеждает последняя
(буфер хранит как dict). На практике: фоновый маркер `IN_QUEUE` и финальный
`DONE_BOT` для одной строки → в Sheets уйдёт только финальный (это ок —
маркеры нужны только для медленных задач, успевающих отвиснуть несколько
циклов).

Каждый flush обернут в `with_retry` — на 429/5xx делаем exponential backoff
с jitter.
"""
from datetime import date

import gspread
import structlog

from app.constants import SHEETS_WRITE_BATCH_ROWS
from app.sheets._rate_limit import acquire_write, with_retry
from app.sheets.reader import get_sheet

log = structlog.get_logger()

# Индексы колонок (1-based, как в gspread)
COL_STATUS = 8          # H
COL_DATE_DONE = 9       # I
COL_NEEDS_ATTENTION = 12  # L
COL_COMMENT = 13        # M

# Буфер: (row, col) -> value. Дублирующие записи перезатираются (last wins).
_pending: dict[tuple[int, int], str] = {}


def _fmt_date(d: date | None) -> str:
    return d.strftime("%d.%m.%y") if d else ""


def _stage(row: int, col: int, value: str) -> None:
    _pending[(row, col)] = value


def update_task_row(
    row: int,
    *,
    status: str | None = None,
    date_done: date | None = None,
    needs_attention: bool | None = None,
    comment: str | None = None,
) -> None:
    """Стейджит изменения в буфер. Пишет в Sheets когда буфер наберёт батч.

    Передавай только те поля, которые нужно изменить.
    row — 1-based номер строки в таблице (строка 1 = заголовок).
    """
    staged = False
    if status is not None:
        _stage(row, COL_STATUS, str(status))
        staged = True
    if date_done is not None:
        _stage(row, COL_DATE_DONE, _fmt_date(date_done))
        staged = True
    if needs_attention is not None:
        _stage(row, COL_NEEDS_ATTENTION, "Да" if needs_attention else "")
        staged = True
    if comment is not None:
        _stage(row, COL_COMMENT, comment)
        staged = True

    if not staged:
        return

    log.info("sheet_row_staged", row=row, buffer_rows=_unique_row_count())

    if _unique_row_count() >= SHEETS_WRITE_BATCH_ROWS:
        flush()


def _unique_row_count() -> int:
    return len({r for (r, _) in _pending.keys()})


def flush() -> None:
    """Сбрасывает буфер в один API-call. Идемпотентно (no-op если буфер пуст)."""
    if not _pending:
        return

    ws = get_sheet("Задания")
    cells = [
        gspread.Cell(row=r, col=c, value=v)
        for (r, c), v in _pending.items()
    ]
    rows_count = _unique_row_count()
    cells_count = len(cells)
    _pending.clear()  # очищаем ДО API call — на случай частичного фейла не зациклимся

    acquire_write()
    with_retry(
        "update_cells",
        lambda: ws.update_cells(cells, value_input_option="RAW"),
    )
    log.info("sheet_batch_flushed", rows=rows_count, cells=cells_count)


def mark_skipped(row: int, reason: str) -> None:
    """Ставит флаг «Требует реакции» и пишет причину в Коментарий."""
    update_task_row(row, needs_attention=True, comment=reason)
