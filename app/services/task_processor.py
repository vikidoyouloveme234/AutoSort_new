"""Ядро обработки заданий.

Цикл (после рефакторинга 2026-04-28 по запросу заказчика):
1. Читаем все строки листа «Задания»
2. Парсим — нормализуем склады, пропускаем мусор
3. Для каждой строки со статусом «Создан» или «В очереди бота»:
   a. Проверяем дедлайн → если просрочен, ставим «Отменен по дедлайну»
   b. Получаем warehouse_id (src + dst) из БД
   c. Если статус был «Создан» — сразу ставим «В очереди бота» в Sheets
      (визуальная индикация что бот взял в работу). Если статус уже
      «В очереди бота» (повторный цикл) — Sheets-write пропускаем,
      обработка продолжается.
   d. Получаем chrtID (из БД-кэша или /stocks при первой встрече nmID)
   e. Отправляем заявку через wb_client (квоту dst НЕ проверяем превентивно —
      submit вернёт `exceeded-quota` если что, обрабатываем реактивно).
   f. На 200 OK → «Выполнен ботом» + дата, на «requestAlreadyInProcess» —
      тоже «Выполнен ботом» (заявка уже в WB). На квоте — оставляем IN_QUEUE
      с комментарием, бот повторит. На прочих ошибках — IN_QUEUE +
      needs_attention.
4. Финальные статусы (DONE_BOT/DONE_MANUAL/DONE_PARTIAL/CANCELLED) — игнорируем.
5. Отслеживание физической доставки (delivery_watcher) отключено —
   заказчик решил, что не нужно.
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
from app.wb_client.auth import invalidate_token_cache
from app.wb_client.client import OrderRequest, OrderResponse, submit_order
from app.wb_client.lk_stocks import fetch_stocks_lk

log = structlog.get_logger()

FINAL_STATUSES = {
    TaskStatus.DONE_BOT,
    TaskStatus.DONE_MANUAL,
    TaskStatus.DONE_PARTIAL,
    TaskStatus.CANCELLED,
}

PROCESSABLE_STATUSES = {TaskStatus.CREATED, TaskStatus.IN_QUEUE}


async def _get_warehouse_id(session: AsyncSession, canonical_name: str) -> int | None:
    result = await session.execute(
        select(Warehouse.wb_warehouse_id).where(Warehouse.canonical_name == canonical_name)
    )
    return result.scalar_one_or_none()


async def _get_known_warehouses(session: AsyncSession) -> set[str]:
    result = await session.execute(select(Warehouse.canonical_name))
    return set(result.scalars().all())


def _should_skip_by_status(task) -> bool:
    """Skip финальные статусы и неизвестные. Process CREATED + IN_QUEUE."""
    status = TaskStatus(task.status) if task.status in TaskStatus._value2member_map_ else None
    if status in FINAL_STATUSES:
        return True
    if status not in PROCESSABLE_STATUSES:
        return True  # пустой/неизвестный статус
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


def _mark_in_queue_if_new(task) -> None:
    """Ставит «В очереди бота» один раз — при первой встрече строки в статусе CREATED.

    На повторных циклах status уже IN_QUEUE — Sheets-write не делаем, экономим
    обращения к Sheets API.
    """
    if task.status != TaskStatus.CREATED.value:
        return
    if not settings.wb_dry_run:
        writer.update_task_row(
            task.row_number,
            status=TaskStatus.IN_QUEUE,
            needs_attention=False,
            comment="",
        )


async def _resolve_chrt_id(
    task, cookie_str: str, authorizev3: str, session: AsyncSession,
) -> int | None:
    """Возвращает chrt_id для nmID, кэш-первый.

    1. Если есть в БД-кэше (`chrt_cache`) — возвращаем мгновенно, без
       запроса к WB. chrt_id почти не меняется (только при смене категории),
       поэтому кэш можно держать долго.
    2. Иначе fetch /stocks → берём chrtID первого склада → пишем в кэш →
       возвращаем.
    3. Если /stocks недоступен (429/network/auth) — None, задача останется
       IN_QUEUE, следующий цикл попробует снова.
    4. Если /stocks вернул пустой список (товара нет нигде) — пишем
       нужное-внимание-комментарий и возвращаем None.
    """
    cached = await get_cached_chrt_id(session, task.nm_id)
    if cached is not None:
        return cached

    stocks = await fetch_stocks_lk(task.nm_id, cookie_str, authorizev3)
    if stocks is None:
        log.warning("task_stocks_unavailable", row=task.row_number)
        if not settings.wb_dry_run:
            writer.update_task_row(
                task.row_number, needs_attention=False,
                comment="Не удалось получить артикул карточки (chrtID), повтор в следующем цикле.",
            )
        return None

    if not stocks:
        if not settings.wb_dry_run:
            writer.update_task_row(
                task.row_number, needs_attention=True,
                comment=f"nmID {task.nm_id} нигде нет на остатках WB.",
            )
        return None

    chrt_id = next(iter(stocks.values())).chrt_id
    await upsert_chrt_cache(session, task.nm_id, chrt_id)
    return chrt_id


async def _handle_submit_response(
    resp: OrderResponse, task, session: AsyncSession,
) -> str:
    """Обрабатывает ответ WB. Возвращает строковый исход:
    - "submitted": 200 OK или requestAlreadyInProcess → DONE_BOT
    - "quota": квота исчерпана → IN_QUEUE с комментарием, бот повторит
    - "network": сетевая/circuit/token-fail — Sheets не трогаем, повторим
    - "stop_expired": 401 → выходим из цикла, куки протухли
    - "failed": прочая ошибка → IN_QUEUE + needs_attention
    """
    if resp.success:
        log.info("task_submitted", row=task.row_number, nm_id=task.nm_id)
        if not settings.wb_dry_run:
            writer.update_task_row(
                task.row_number, status=TaskStatus.DONE_BOT,
                date_done=date.today(), needs_attention=False, comment="",
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
        # Заявка уже в системе WB → с точки зрения «отправлено» она готова.
        # Заказчик подтвердил: ставим DONE_BOT, не зацикливаемся на повторах.
        log.info("task_already_in_process", row=task.row_number, nm_id=task.nm_id)
        if not settings.wb_dry_run:
            writer.update_task_row(
                task.row_number, status=TaskStatus.DONE_BOT,
                date_done=date.today(), needs_attention=False,
                comment="Заявка уже в очереди WB.",
            )
        return "submitted"

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

    Возможные исходы: "skipped"/"cancelled"/"submitted"/"quota"/"network"/"stop_expired"/"failed".
    Вызывающий различает только "submitted" (считать в processed) и "stop_expired" (break).
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

    # Ранний маркер «В очереди бота» — только при первом увиденнии строки
    # (status == CREATED). На последующих циклах status уже IN_QUEUE,
    # лишний Sheets-write не делаем.
    _mark_in_queue_if_new(task)

    chrt_id = await _resolve_chrt_id(task, cookie_str, authorizev3, session)
    if chrt_id is None:
        return "skipped"

    expected_qty = task.quantity or 1

    # NB: pre-check квоты dst (`fetch_quota`) убран 2026-04-28 — submit_order
    # сам вернёт `exceeded-quota` при недостатке, и `_quota_exceeded_side`
    # это корректно ловит. Минус 1 запрос на задачу = ~33% throughput.

    order = OrderRequest(
        src_warehouse_id=src_id, dst_warehouse_id=dst_id,
        nm_id=task.nm_id, chrt_id=chrt_id, count=expected_qty,
    )
    resp = await submit_order(order, cookie_str, authorizev3)
    return await _handle_submit_response(resp, task, session)


async def process_once(session: AsyncSession) -> int:
    """Один цикл обработки. Возвращает число успешно сабмиченных заявок."""
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
