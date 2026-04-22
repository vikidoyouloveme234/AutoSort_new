"""Вычисление статистики из данных Google Sheets.

Данные кешируются в памяти на 5 минут.
Три периода: неделя / месяц / всё время.
Семь метрик по ТЗ.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.db.models.task import TaskStatus
from app.sheets import parser, reader
from app.sheets.parser import ParsedTask

from app.constants import STATS_CACHE_TTL_SEC as CACHE_TTL

_FINAL_DONE = frozenset({TaskStatus.DONE_BOT, TaskStatus.DONE_MANUAL, TaskStatus.DONE_PARTIAL})

_cache: dict = {}


@dataclass
class PeriodStats:
    """Семь метрик за один период."""
    total: int = 0          # 1. Количество заданий
    units: int = 0          # 2. Всего перемещённых штук
    done: int = 0           # для расчёта % успеха
    in_queue: int = 0       # 6. В работе сейчас
    cancelled: int = 0      # 7. Отменено по дедлайну
    by_src: Counter = field(default_factory=Counter)   # 4. По складам отгрузки
    by_dst: Counter = field(default_factory=Counter)   # 5. По складам прихода
    by_manager: dict[str, "ManagerStats"] = field(default_factory=dict)

    @property
    def success_pct(self) -> float:         # 3. % успеха
        return round(self.done / self.total * 100, 1) if self.total else 0.0


@dataclass
class ManagerStats:
    """Статистика на одного менеджера — все 7 метрик из ТЗ."""
    total: int = 0
    units: int = 0
    done: int = 0
    cancelled: int = 0
    in_queue: int = 0
    by_src: Counter = field(default_factory=Counter)
    by_dst: Counter = field(default_factory=Counter)

    @property
    def success_pct(self) -> float:
        return round(self.done / self.total * 100, 1) if self.total else 0.0


def get_tasks(known: set[str]) -> list[ParsedTask]:
    """Читает таблицу «Задания» с кешем 5 минут."""
    now = datetime.now()
    if _cache.get("tasks") and (now - _cache["ts"]).total_seconds() < CACHE_TTL:
        return _cache["tasks"]  # type: ignore[return-value]

    raw = reader.read_tasks_raw()
    tasks, _ = parser.parse_tasks(raw[1:], known)
    _cache["tasks"] = tasks
    _cache["ts"] = now
    return tasks


def invalidate_cache() -> None:
    """Сбросить кеш — вызывать после ручного запуска process_once."""
    _cache.clear()


def _cutoff(period: str) -> date | None:
    today = date.today()
    if period == "week":
        return today - timedelta(days=7)
    if period == "month":
        return today - timedelta(days=30)
    return None  # "all"


def compute_stats(tasks: list[ParsedTask], period: str) -> PeriodStats:
    """Считает все 7 метрик за указанный период — глобально и по каждому менеджеру."""
    cutoff = _cutoff(period)
    s = PeriodStats()

    # Метрика 6: «в работе» — всегда текущий снимок, без фильтра периода
    for t in tasks:
        if t.status != TaskStatus.IN_QUEUE:
            continue
        s.in_queue += 1
        mgr = (t.responsible or "—").strip() or "—"
        if mgr not in s.by_manager:
            s.by_manager[mgr] = ManagerStats()
        s.by_manager[mgr].in_queue += 1

    for t in tasks:
        if t.status == TaskStatus.IN_QUEUE:
            continue

        # Фильтр по периоду: для выполненных — date_done, для остальных — date_added
        ref = t.date_done if t.status in _FINAL_DONE else t.date_added
        if cutoff and (ref is None or ref < cutoff):
            continue

        s.total += 1

        if t.status in _FINAL_DONE:
            s.done += 1
            s.units += t.quantity or 0
            s.by_src[t.warehouse_src or "—"] += 1
            s.by_dst[t.warehouse_dst or "—"] += 1
        elif t.status == TaskStatus.CANCELLED:
            s.cancelled += 1

        mgr = (t.responsible or "—").strip() or "—"
        if mgr not in s.by_manager:
            s.by_manager[mgr] = ManagerStats()
        m = s.by_manager[mgr]
        m.total += 1
        if t.status in _FINAL_DONE:
            m.done += 1
            m.units += t.quantity or 0
            m.by_src[t.warehouse_src or "—"] += 1
            m.by_dst[t.warehouse_dst or "—"] += 1
        elif t.status == TaskStatus.CANCELLED:
            m.cancelled += 1

    # Сортируем менеджеров по общему числу заданий
    s.by_manager = dict(
        sorted(s.by_manager.items(), key=lambda kv: kv[1].total, reverse=True)
    )
    return s
