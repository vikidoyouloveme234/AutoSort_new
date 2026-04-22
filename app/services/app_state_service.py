"""Сервис управления состоянием бота (singleton-строка app_state id=1).

Используется:
- Планировщиком: `is_bot_enabled()` перед каждым poll_tasks → если паузa, skip
- Роутером: pause/resume/set_interval endpoints
- Дашбордом: показать last_success_at, last_error_text, bot_enabled
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.app_state import AppState


async def get_state(session: AsyncSession) -> AppState:
    """Возвращает singleton-строку состояния. Создаёт если отсутствует."""
    result = await session.execute(select(AppState).where(AppState.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = AppState(id=1, bot_enabled=True, poll_interval_minutes=5)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def set_bot_enabled(session: AsyncSession, enabled: bool) -> None:
    state = await get_state(session)
    state.bot_enabled = enabled
    await session.commit()


async def set_poll_interval(session: AsyncSession, minutes: int) -> None:
    if minutes < 1 or minutes > 60:
        raise ValueError("poll_interval_minutes должен быть в [1, 60]")
    state = await get_state(session)
    state.poll_interval_minutes = minutes
    await session.commit()


async def record_poll_success(session: AsyncSession, processed: int) -> None:
    """Вызывать в конце успешного process_once.

    ВАЖНО: last_error_at/last_error_text НЕ чистятся — ошибка остаётся видна
    в истории до явной очистки через clear_last_error. Это сохраняет аудит-след
    даже если бот восстановился.
    """
    state = await get_state(session)
    state.last_success_at = datetime.now()
    state.last_success_processed = processed
    await session.commit()


async def clear_last_error(session: AsyncSession) -> None:
    """Очистить информацию о последней ошибке (админ-действие)."""
    state = await get_state(session)
    state.last_error_at = None
    state.last_error_text = None
    await session.commit()


async def record_poll_error(session: AsyncSession, error_text: str) -> None:
    state = await get_state(session)
    state.last_error_at = datetime.now()
    state.last_error_text = error_text[:1000]  # обрезаем, чтоб не переполнить TEXT
    await session.commit()


async def bump_session_version(session: AsyncSession) -> int:
    """Инкрементирует session_version в БД и возвращает новое значение.

    Вызывается из админ-кнопки «Сбросить все сессии» — после этого все cookies
    становятся невалидными (проверка в auth._make_token по session_version).
    """
    state = await get_state(session)
    state.session_version += 1
    new_version = state.session_version
    await session.commit()
    return new_version


async def run_with_tracking(operation, label: str = "poll_tasks") -> None:
    """Запускает operation() с записью результата в app_state.

    Используется и scheduler-job'ом (jobs.poll_tasks), и ручным запуском из UI
    (_run_process_once в router). Гарантирует что обе точки обновляют last_success_at.
    """
    import structlog
    from app.db.session import AsyncSessionLocal

    log = structlog.get_logger()

    async with AsyncSessionLocal() as session:
        try:
            processed = await operation(session)
        except Exception as e:
            log.exception(f"{label}_failed")
            async with AsyncSessionLocal() as s2:
                await record_poll_error(s2, f"{type(e).__name__}: {e}")
            return
        async with AsyncSessionLocal() as s2:
            await record_poll_success(s2, processed or 0)
