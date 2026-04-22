"""Парсер строк листа «Задания».

Правила:
- strip() все поля
- Пустой «Склад получения» (F) → пропуск строки, флаг «Требует реакции»
- Aliases складов: «СПБ» → «Склад Шушары», «Екатеринбург» → «Екатеринбург - Перспективная 14»
- Если склад не найден → пропуск, комментарий «Не распознан склад: <value>»
- Артикулы: strip() + пропускать пустой nmID
"""
from dataclasses import dataclass
from datetime import date

import structlog

log = structlog.get_logger()

# Подтверждено заказчиком 2026-04-16 + из реальных данных таблицы
WAREHOUSE_ALIASES: dict[str, str] = {
    "спб": "Склад Шушары",
    "екатеринбург": "Екатеринбург - Перспективная 14",
    "новосемейкино": "Самара (Новосемейкино)",
    "новосиб": "Новосибирск",
    "рязань": "Рязань (Тюшевское)",
}


@dataclass
class ParsedTask:
    row_number: int
    article: str
    responsible: str
    date_added: date | None
    nm_id: int | None
    warehouse_src: str
    warehouse_dst: str
    quantity: int | None
    status: str
    date_done: date | None  # col I — ставит бот
    deadline: date | None   # col J
    needs_attention: bool = False  # col L — флаг требует реакции (ставит бот при ошибках)
    comment: str = ""              # col M — текст ошибки или примечание


@dataclass
class SkippedRow:
    row_number: int
    reason: str
    needs_attention: bool = True


def normalize_warehouse(raw: str) -> str | None:
    """Возвращает канонное название склада или None если не найден."""
    stripped = raw.strip()
    lower = stripped.lower()
    if lower in WAREHOUSE_ALIASES:
        return WAREHOUSE_ALIASES[lower]
    return stripped if stripped else None


def parse_date(raw: str) -> date | None:
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    log.warning("parse_date_failed", raw=raw)
    return None


def parse_tasks(
    rows: list[list[str]],
    known_warehouses: set[str],
) -> tuple[list[ParsedTask], list[SkippedRow]]:
    """Парсит строки листа «Задания» (без заголовка, row_number — 1-based в таблице)."""
    tasks: list[ParsedTask] = []
    skipped: list[SkippedRow] = []

    for i, row in enumerate(rows, start=2):  # строка 1 — заголовок
        # Дополняем до 13 колонок
        row = (row + [""] * 13)[:13]
        article, responsible, date_added_raw, nm_id_raw, src_raw, dst_raw, qty_raw, status = row[:8]
        date_done_raw = row[8]   # col I
        deadline_raw  = row[9]   # col J
        # col K (idx 10) — формула, бот не трогает
        needs_attention_raw = row[11]  # col L
        comment_raw = row[12]          # col M

        article = article.strip()
        responsible = responsible.strip()
        status = status.strip()
        needs_attention = needs_attention_raw.strip().lower() == "да"
        comment = comment_raw.strip()

        # Пустой склад получения → пропуск
        if not dst_raw.strip():
            skipped.append(SkippedRow(i, "Пустой склад получения", needs_attention=True))
            continue

        warehouse_dst = normalize_warehouse(dst_raw)
        warehouse_src = normalize_warehouse(src_raw) or src_raw.strip()

        if warehouse_dst is None:
            skipped.append(SkippedRow(i, f"Не распознан склад: {dst_raw.strip()}", needs_attention=True))
            continue

        if warehouse_dst not in known_warehouses:
            skipped.append(SkippedRow(i, f"Не распознан склад: {warehouse_dst}", needs_attention=True))
            continue

        nm_id: int | None = None
        if nm_id_raw.strip():
            try:
                nm_id = int(nm_id_raw.strip())
            except ValueError:
                log.warning("bad_nm_id", row=i, value=nm_id_raw)

        qty: int | None = None
        if qty_raw.strip():
            try:
                qty = int(qty_raw.strip())
            except ValueError:
                log.warning("bad_qty", row=i, value=qty_raw)

        tasks.append(ParsedTask(
            row_number=i,
            article=article,
            responsible=responsible,
            date_added=parse_date(date_added_raw),
            nm_id=nm_id,
            warehouse_src=warehouse_src,
            warehouse_dst=warehouse_dst,
            quantity=qty,
            status=status,
            date_done=parse_date(date_done_raw),
            deadline=parse_date(deadline_raw),
            needs_attention=needs_attention,
            comment=comment,
        ))

    return tasks, skipped
