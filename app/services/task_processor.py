"""Ядро обработки заданий.

Цикл:
1. Читаем все строки листа «Задания»
2. Парсим — нормализуем склады, пропускаем мусор
3. Для каждой строки со статусом «Создан»:
   a. Проверяем дедлайн → если просрочен, ставим «Отменен по дедлайну»
   b. Получаем warehouse_id (src + dst) из БД
   c. Получаем chrtID по nmID
   d. Отправляем заявку через wb_client
   e. Обновляем статус в Sheets и в БД
4. «В очереди бота» — не трогаем (доделывает WB сам, до 72 часов)
5. Финальные статусы — игнорируем
"""
from datetime import date

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.task import TaskStatus
from app.db.models.warehouse import Warehouse
from app.services.chrt_cache_service import get_cached_chrt_id, upsert_chrt_cache
from app.services.cookie_service import get_decrypted_credentials, mark_cookie_health
from app.sheets import parser, reader, writer
from app.wb_client._stocks_cache import fetch_stocks_lk_cached
from app.wb_client.auth import invalidate_token_cache
from app.wb_client.client import OrderRequest, OrderResponse, submit_order
from app.wb_client.lk_stocks import fetch_quota

log = structlog.get_logger()

FINAL_STATUSES = {
    TaskStatus.DONE_BOT,
    TaskStatus.DONE_MANUAL,
    TaskStatus.DONE_PARTIAL,
}


async def _get_warehouse_id(session: AsyncSession, canonical_name: str) -> int | None:
    result = await session.execute(
        select(Warehouse.wb_warehouse_id).where(Warehouse.canonical_name == canonical_name)
    )
    return result.scalar_one_or_none()


async def _get_known_warehouses(session: AsyncSession) -> set[str]:
    result = await session.execute(select(Warehouse.canonical_name))
    return set(result.scalars().all())


def _should_skip_by_status(task) -> bool:
    """True если задача не в статусе «Создан» (финальные, IN_QUEUE, пустой)."""
    status = TaskStatus(task.status) if task.status in TaskStatus._value2member_map_ else None
    if status in FINAL_STATUSES or status == TaskStatus.IN_QUEUE:
        return True
    if status != TaskStatus.CREATED:
        return True
    return False


def _handle_deadline_passed(task, today: date) -> bool:
    """Отмечает строку отменённой если дедлайн прошёл. True = отменили, идём дальше."""
    if not task.deadline or today <= task.deadline:
        return False
    log.info("task_cancelled_deadline", row=task.row_number)
    if not settings.wb_dry_run:
        writer.update_task_row(
            task.row_number,
            status=TaskStatus.CANCELLED,
            comment="Отменено по дедлайну",
        )
    return True


async def _resolve_warehouses(task, session: AsyncSession) -> tuple[int, int] | None:
    """Резолвит src/dst warehouse IDs. None + mark_skipped — если не нашли."""
    src_id = await _get_warehouse_id(session, task.warehouse_src)
    dst_id = await _get_warehouse_id(session, task.warehouse_dst)
    if src_id is None:
        _skip(task.row_number, f"Не найден warehouse_id: {task.warehouse_src}")
        return None
    if dst_id is None:
        _skip(task.row_number, f"Не найден warehouse_id: {task.warehouse_dst}")
        return None
    return src_id, dst_id


def _skip(row: int, reason: str) -> None:
    log.warning("row_skipped", row=row, reason=reason)
    if not settings.wb_dry_run:
        writer.mark_skipped(row, reason)


async def _resolve_chrt_and_baseline(
    task, dst_id: int, cookie_str: str, authorizev3: str, session: AsyncSession,
) -> tuple[int, int] | None:
    """Получает chrt_id и baseline на dst.

    Путь:
    1. In-memory TTL-кэш /stocks (fetch_stocks_lk_cached) — даёт и chrt_id, и baseline.
    2. Успех → сохраняем chrt_id в БД-кэш (ChrtCache) для будущего fallback.
    3. Fail (/stocks недоступен) → пробуем БД-кэш с baseline=0 (watcher деградированно).
    4. И БД-кэш пуст → None (задача остаётся «Создан», next cycle повторит).
    """
    stocks = await fetch_stocks_lk_cached(task.nm_id, cookie_str, authorizev3)

    if stocks is None:
        # API сдох (429 / network после ретраев). Пробуем last-resort БД-кэш.
        cached_chrt = await get_cached_chrt_id(session, task.nm_id)
        if cached_chrt is not None:
            log.warning(
                "task_stocks_unavailable_using_db_fallback",
                row=task.row_number, nm_id=task.nm_id, chrt_id=cached_chrt,
            )
            return cached_chrt, 0  # baseline=0 → watcher отметит DONE при любом приходе
        log.warning("task_stocks_unavailable", row=task.row_number)
        return None

    if not stocks:
        _skip(task.row_number, f"nmID {task.nm_id} нигде нет на остатках")
        return None

    chrt_id = next(iter(stocks.values())).chrt_id
    baseline_qty = stocks[dst_id].count if dst_id in stocks else 0
    await upsert_chrt_cache(session, task.nm_id, chrt_id)
    return chrt_id, baseline_qty


async def _quota_allows(
    task, dst_id: int, expected_qty: int, cookie_str: str, authorizev3: str,
) -> bool:
    """Проверяет квоту dst. Если явно недостаточна — skip + False. Иначе True
    (None от API трактуем как 'может быть можно', идём дальше)."""
    quota_dst = await fetch_quota(dst_id, "dst", cookie_str, authorizev3)
    if quota_dst is not None and quota_dst < expected_qty:
        log.info("task_dst_quota_insufficient", row=task.row_number,
                 quota=quota_dst, expected=expected_qty)
        if not settings.wb_dry_run:
            writer.mark_skipped(
                task.row_number,
                f"Квота склада-получателя исчерпана (доступно {quota_dst}, нужно {expected_qty})",
            )
        return False
    return True


async def _handle_submit_response(
    resp: OrderResponse, task, chrt_id: int, dst_id: int, baseline_qty: int,
    expected_qty: int, session: AsyncSession,
) -> str:
    """Обрабатывает ответ WB. Возвращает:
    - "submitted": всё OK, TaskDelivery создана, Sheets обновлён
    - "already": дубль, Sheets помечен IN_QUEUE, TaskDelivery не создана
    - "quota": квота исчерпана, оставлено как «Создан» (retry в окно)
    - "network": сетевая/circuit/token-fail — не трогаем Sheets
    - "stop_expired": 401 → вышли из цикла
    - "failed": прочая ошибка → needs_attention
    """
    if resp.success:
        log.info("task_submitted", row=task.row_number, nm_id=task.nm_id)
        await _record_delivery(
            session=session,
            sheet_row=task.row_number,
            nm_id=task.nm_id,
            chrt_id=chrt_id,
            dst_warehouse_id=dst_id,
            expected_quantity=expected_qty,
            baseline=baseline_qty,
        )
        if not settings.wb_dry_run:
            writer.update_task_row(
                task.row_number, status=TaskStatus.IN_QUEUE,
                needs_attention=False, comment="",
            )
        return "submitted"

    if resp.status_code == 401:
        invalidate_token_cache()
        await mark_cookie_health(session, "expired")
        log.error("cookie_expired_stopping")
        return "stop_expired"

    if resp.status_code == 0:
        log.warning("task_network_retry", row=task.row_number)
        return "network"

    if _is_already_in_process(resp):
        log.info("task_already_in_process", row=task.row_number, nm_id=task.nm_id)
        if not settings.wb_dry_run:
            writer.update_task_row(
                task.row_number, status=TaskStatus.IN_QUEUE,
                needs_attention=False, comment="Заявка уже в очереди WB",
            )
        return "already"

    side = _quota_exceeded_side(resp)
    if side is not None:
        side_text = "источника" if side == "src" else "получателя"
        log.info("task_quota_exceeded", row=task.row_number, side=side)
        if not settings.wb_dry_run:
            writer.update_task_row(
                task.row_number, needs_attention=False,
                comment=f"Квота склада-{side_text} исчерпана. Повтор в окно квот (00:00/09:00/18:00 МСК).",
            )
        return "quota"

    log.warning("task_failed", row=task.row_number, status=resp.status_code, body=resp.body)
    if not settings.wb_dry_run:
        writer.update_task_row(
            task.row_number, needs_attention=True,
            comment=f"Ошибка WB {resp.status_code}: {resp.body.get('errorText', '')}",
        )
    return "failed"


async def _process_single_task(
    task, today: date, cookie_str: str, authorizev3: str, session: AsyncSession,
) -> str:
    """Полный жизненный цикл одной строки. Возвращает статус-результат.

    Возможные статусы: "skipped"/"cancelled"/"submitted"/"already"/"quota"/"network"/"stop_expired"/"failed"
    Вызывающий должен различать только "submitted" (считать в processed) и "stop_expired" (break).
    """
    if _should_skip_by_status(task):
        return "skipped"

    if _handle_deadline_passed(task, today):
        return "cancelled"

    if not task.nm_id:
        _skip(task.row_number, "Нет nmID")
        return "skipped"

    warehouses = await _resolve_warehouses(task, session)
    if warehouses is None:
        return "skipped"
    src_id, dst_id = warehouses

    stock_info = await _resolve_chrt_and_baseline(task, dst_id, cookie_str, authorizev3, session)
    if stock_info is None:
        return "skipped"
    chrt_id, baseline_qty = stock_info

    expected_qty = task.quantity or 1
    if not await _quota_allows(task, dst_id, expected_qty, cookie_str, authorizev3):
        return "skipped"

    order = OrderRequest(
        src_warehouse_id=src_id, dst_warehouse_id=dst_id,
        nm_id=task.nm_id, chrt_id=chrt_id, count=expected_qty,
    )
    resp = await submit_order(order, cookie_str, authorizev3)
    return await _handle_submit_response(
        resp, task, chrt_id, dst_id, baseline_qty, expected_qty, session,
    )


async def process_once(session: AsyncSession) -> int:
    """Один цикл обработки: читает таблицу и обрабатывает новые задания.

    Возвращает число успешно сабмиченных заявок (для app_state.last_success_processed).
    """
    log.info("process_cycle_start")

    known = await _get_known_warehouses(session)
    raw_rows = reader.read_tasks_raw()
    if len(raw_rows) <= 1:
        log.info("no_rows")
        return 0

    tasks, skipped = parser.parse_tasks(raw_rows[1:], known)

    for skip in skipped:
        _skip(skip.row_number, skip.reason)

    today = date.today()
    creds = await get_decrypted_credentials(session)
    if creds is None:
        log.error("no_active_cookie")
        return 0
    cookie_str, authorizev3 = creds

    processed = 0
    for task in tasks:
        result = await _process_single_task(task, today, cookie_str, authorizev3, session)
        if result == "submitted":
            processed += 1
        elif result == "stop_expired":
            break

    log.info("process_cycle_done", processed=processed)
    return processed


def _is_already_in_process(resp: OrderResponse) -> bool:
    """WB-код: заявка уже создана ранее, дубль не принят.

    Дедуп на уровне (nmID, src, dst) — без учёта chrtID и quantity.
    Подтверждено живыми запросами 2026-04-18.
    """
    return (
        isinstance(resp.body, dict)
        and resp.body.get("errorText") == "requestAlreadyInProcess"
    )


def _quota_exceeded_side(resp: OrderResponse) -> str | None:
    """WB-код: квота склада исчерпана. Возвращает 'src'/'dst' или None.

    Подтверждено живым запросом 2026-04-18:
    `{"errorText": "exceeded-quota", "additionalErrors": {"placement": ["srcOffice"]}}`
    """
    if not isinstance(resp.body, dict):
        return None
    if resp.body.get("errorText") != "exceeded-quota":
        return None
    placement = (resp.body.get("additionalErrors") or {}).get("placement", [])
    if "srcOffice" in placement:
        return "src"
    if "dstOffice" in placement:
        return "dst"
    return None


async def _record_delivery(
    session: AsyncSession,
    sheet_row: int,
    nm_id: int,
    chrt_id: int,
    dst_warehouse_id: int,
    expected_quantity: int,
    baseline: int,
) -> None:
    """Создаёт (или обновляет если повторная подача) запись TaskDelivery."""
    from app.db.models.delivery import TaskDelivery

    existing = await session.execute(
        select(TaskDelivery).where(TaskDelivery.sheet_row == sheet_row)
    )
    row = existing.scalar_one_or_none()
    if row is None:
        row = TaskDelivery(
            sheet_row=sheet_row,
            nm_id=nm_id,
            chrt_id=chrt_id,
            dst_warehouse_id=dst_warehouse_id,
            expected_quantity=expected_quantity,
            dst_qty_baseline=baseline,
        )
        session.add(row)
    else:
        # Повторная подача — обнуляем verified_at и обновляем baseline
        row.nm_id = nm_id
        row.chrt_id = chrt_id
        row.dst_warehouse_id = dst_warehouse_id
        row.expected_quantity = expected_quantity
        row.dst_qty_baseline = baseline
        row.verified_at = None
    await session.commit()


