from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.config import settings
from app.scheduler.jobs import scheduler, start_scheduler
from app.web.router import router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", dry_run=settings.wb_dry_run)
    if settings.wb_dry_run:
        log.warning("DRY RUN mode is ON — no real requests will be sent to WB")

    # Загружаем текущую версию admin-сессий из БД (revoke-механизм)
    from app.db.session import AsyncSessionLocal
    from app.services.app_state_service import get_state
    from app.web.auth import set_current_session_version
    async with AsyncSessionLocal() as session:
        state = await get_state(session)
        set_current_session_version(state.session_version)

    await start_scheduler()
    yield
    scheduler.shutdown(wait=False)
    log.info("shutdown")


app = FastAPI(title="Auto Sort — WB redistribution", version="0.1.0", lifespan=lifespan)
app.include_router(router)
