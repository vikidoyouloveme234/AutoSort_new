"""Наблюдатель доставок.

Раз в сутки (07:00 МСК): для записей в task_deliveries (verified_at IS NULL,
submitted_at < 7d) дёргает `/stocks?nmID=` через ЛК-куки и сравнивает текущий
count на dst-складе с baseline. Если delta >= expected → DONE_BOT, >= 90% → DONE_PARTIAL.

Почему раз в сутки: физическое перемещение WB между складами занимает 1-3 дня,
час или два задержки детекта приезда роли не играют.
"""
from datetime import date, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.delivery import TaskDelivery
from app.db.models.task import TaskStatus
from app.services.cookie_service import get_decrypted_credentials
from app.sheets import writer
from app.wb_client.lk_stocks import fetch_stocks_lk

log = structlog.get_logger()

from app.constants import PARTIAL_THRESHOLD, WATCH_WINDOW_DAYS  # noqa: E402


async def check_deliveries(session: AsyncSession) -> None:
    """Проверяет все незавершённые доставки и обновляет Sheets."""
    cutoff = datetime.now() - timedelta(days=WATCH_WINDOW_DAYS)

    result = await session.execute(
        select(TaskDelivery)
        .where(TaskDelivery.verified_at.is_(None))
        .where(TaskDelivery.submitted_at >= cutoff)
    )
    pending = list(result.scalars().all())
    if not pending:
        log.info("delivery_watch_no_pending")
        return

    creds = await get_decrypted_credentials(session)
    if creds is None:
        log.warning("delivery_watch_no_cookie")
        return
    cookie_str, authorizev3 = creds

    log.info("delivery_watch_start", pending=len(pending))

    # Дедуплицируем по nm_id — один /stocks-запрос на все доставки одного товара
    stocks_per_nm: dict[int, dict[int, int] | None] = {}
    for nm_id in {d.nm_id for d in pending}:
        result = await fetch_stocks_lk(nm_id, cookie_str, authorizev3)
        if result is None:
            log.warning("delivery_watch_stocks_failed", nm_id=nm_id)
            stocks_per_nm[nm_id] = None
            continue
        # warehouse_id → count (для безразмерных count в первой записи inStock)
        stocks_per_nm[nm_id] = {wh_id: ws.count for wh_id, ws in result.items()}

    today = date.today()
    updated = 0
    partial = 0
    for d in pending:
        wh_counts = stocks_per_nm.get(d.nm_id)
        if wh_counts is None:
            continue  # API упал — пропустим, проверим в следующий час
        current = wh_counts.get(d.dst_warehouse_id, 0)
        delta = current - d.dst_qty_baseline
        if delta <= 0:
            continue

        if delta >= d.expected_quantity:
            d.verified_at = datetime.now()
            updated += 1
            if not settings.wb_dry_run:
                # Сбрасываем needs_attention/comment — задача перешла в финальный успех,
                # старые алерты больше не актуальны.
                writer.update_task_row(
                    d.sheet_row,
                    status=TaskStatus.DONE_BOT,
                    date_done=today,
                    needs_attention=False,
                    comment="",
                )
            log.info("delivery_verified", sheet_row=d.sheet_row, delta=delta, expected=d.expected_quantity)
        elif delta >= int(d.expected_quantity * PARTIAL_THRESHOLD):
            d.verified_at = datetime.now()
            partial += 1
            if not settings.wb_dry_run:
                # DONE_PARTIAL — комментарий с фактом доезда, needs_attention не нужен.
                writer.update_task_row(
                    d.sheet_row,
                    status=TaskStatus.DONE_PARTIAL,
                    date_done=today,
                    needs_attention=False,
                    comment=f"Доехало {delta} из {d.expected_quantity}",
                )
            log.info("delivery_partial", sheet_row=d.sheet_row, delta=delta, expected=d.expected_quantity)

    await session.commit()
    log.info("delivery_watch_done", verified=updated, partial=partial)
