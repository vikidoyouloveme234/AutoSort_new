"""APScheduler jobs.

Триггеры:
1. poll_tasks — каждые N минут читает «Задания» и запускает обработку.
   Интервал читается из app_state.poll_interval_minutes. Job проверяет
   app_state.bot_enabled перед запуском: если пауза, skip (кроме ручного запуска).
2. slot_rush — в 00:00 / 09:00 / 18:00 МСК стартует немедленный опрос.
3. daily_cookie_check — в 08:00 МСК проверяет живость сессии WB.
4. daily_delivery_check — в 07:00 МСК проверяет фактический приход товара.

Race-condition: в :00 минуты часа poll_tasks (5-min interval) и slot_rush
(cron) могут сработать одновременно → параллельный process_once с риском
IntegrityError на task_deliveries. Плюс ручной запуск из UI не должен накладываться
на scheduled. Общая защита — `run_lock.try_acquire()`.
"""
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

log = structlog.get_logger()

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

POLL_JOB_ID = "poll_tasks"
DEFAULT_POLL_INTERVAL_MINUTES = 5


async def poll_tasks() -> None:
    """Читает лист «Задания» и обрабатывает строки со статусом «Создан».

    Перед выполнением проверяет app_state.bot_enabled. Защищено от concurrent
    запусков (slot_rush, manual run) через run_lock.try_acquire — атомарный
    bool-флаг без TOCTOU-окна.
    """
    from app.services.run_lock import release, try_acquire

    # Атомарная проверка-и-захват. Если занят — сразу выходим.
    if not try_acquire():
        log.info("poll_tasks_skipped_already_running")
        return
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.app_state_service import get_state, run_with_tracking
        from app.services.task_processor import process_once

        async with AsyncSessionLocal() as session:
            state = await get_state(session)
            if not state.bot_enabled:
                log.info("poll_tasks_skipped_paused")
                return

        log.info("poll_tasks_start")
        await run_with_tracking(process_once, label="poll_tasks")
        log.info("poll_tasks_done")
    finally:
        release()


async def slot_rush() -> None:
    """Окна броней квот складов — сразу запускаем poll для борьбы за слоты."""
    log.info("slot_rush")
    await poll_tasks()


async def daily_cookie_check() -> None:
    """08:00 МСК — проверяет работоспособность сессии WB."""
    from app.db.session import AsyncSessionLocal
    from app.services.cookie_service import check_cookie_health

    log.info("daily_cookie_check_start")
    async with AsyncSessionLocal() as session:
        health = await check_cookie_health(session)
    log.info("daily_cookie_check_done", health=health)


async def daily_delivery_check() -> None:
    """07:00 МСК — проверяет приход товара на dst-склады через /stocks."""
    from app.db.session import AsyncSessionLocal
    from app.services.delivery_watcher import check_deliveries

    async with AsyncSessionLocal() as session:
        await check_deliveries(session)


async def daily_dead_letter_scan() -> None:
    """07:30 МСК — ищет «забытые» строки с needs_attention, залогировать на видное место.

    Любая строка с `Требует реакции=Да`, которая **старше N дней** с момента добавления,
    попадает сюда как громкий WARNING в логах. Менеджер должен либо принять меры,
    либо пометить как Отменено. Это защита от «висящих» задач в том же Sheets.
    """
    from datetime import date, timedelta

    from sqlalchemy import select
    from app.constants import DEAD_LETTER_AGE_DAYS
    from app.db.models.warehouse import Warehouse
    from app.db.session import AsyncSessionLocal
    from app.web import stats as stats_module

    async with AsyncSessionLocal() as session:
        known_result = await session.execute(select(Warehouse.canonical_name))
        known: set[str] = set(known_result.scalars().all())

    tasks = stats_module.get_tasks(known)
    cutoff = date.today() - timedelta(days=DEAD_LETTER_AGE_DAYS)
    old_attention = [
        t for t in tasks
        if t.needs_attention and t.date_added and t.date_added <= cutoff
    ]

    if old_attention:
        log.warning(
            "dead_letter_escalation",
            count=len(old_attention),
            age_threshold_days=DEAD_LETTER_AGE_DAYS,
            rows=[{"row": t.row_number, "nm_id": t.nm_id, "comment": t.comment} for t in old_attention[:20]],
        )
    else:
        log.info("dead_letter_scan_clean")


async def start_scheduler() -> None:
    """Стартует планировщик. Интервал poll_tasks читает из app_state.

    `max_instances=1` + `coalesce=True` для poll_tasks и slot_rush: предотвращает
    параллельный запуск одного и того же job'а (race condition при совпадении
    :00 минут с slot_rush). Если предыдущий не завершился, новый тик skip'ается.
    """
    from app.db.session import AsyncSessionLocal
    from app.services.app_state_service import get_state

    async with AsyncSessionLocal() as session:
        state = await get_state(session)
        interval = state.poll_interval_minutes

    scheduler.add_job(
        poll_tasks, IntervalTrigger(minutes=interval),
        id=POLL_JOB_ID, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        slot_rush, CronTrigger(hour="0,9,18", minute=0),
        id="slot_rush", max_instances=1, coalesce=True,
    )
    scheduler.add_job(daily_cookie_check, CronTrigger(hour=8, minute=0), id="daily_cookie_check")
    scheduler.add_job(daily_delivery_check, CronTrigger(hour=7, minute=0), id="daily_delivery_check")
    scheduler.add_job(daily_dead_letter_scan, CronTrigger(hour=7, minute=30), id="daily_dead_letter_scan")
    scheduler.start()
    log.info("scheduler_started", poll_interval_min=interval)


def reschedule_poll(minutes: int) -> None:
    """Меняет интервал poll_tasks на лету (вызывается из роутера после смены настройки)."""
    scheduler.reschedule_job(POLL_JOB_ID, trigger=IntervalTrigger(minutes=minutes))
    log.info("poll_tasks_rescheduled", minutes=minutes)
