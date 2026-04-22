"""FastAPI роутер — страницы админ-панели."""
from datetime import datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.config import settings
from app.constants import (
    ACTION_RATE_LIMIT_ATTEMPTS,
    ACTION_RATE_LIMIT_WINDOW_SEC,
    LOGIN_RATE_LIMIT_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW_SEC,
)
from app.web import stats as stats_module
from app.web.auth import get_csrf_token, is_authenticated, set_csrf_cookie, set_session, verify_csrf
from app.web.rate_limit import check_rate_limit

log = structlog.get_logger()
router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

_PERIODS = ("week", "month", "all")


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def _forbidden_csrf() -> JSONResponse:
    return JSONResponse({"error": "CSRF validation failed"}, status_code=403)


def _too_many_requests() -> JSONResponse:
    return JSONResponse({"error": "Too many requests, try again later"}, status_code=429)


def _check_action_limit(request: Request) -> bool:
    return check_rate_limit(
        request,
        bucket="action",
        max_attempts=ACTION_RATE_LIMIT_ATTEMPTS,
        window_sec=ACTION_RATE_LIMIT_WINDOW_SEC,
    )


def _format_verified(verified_at: datetime | None) -> tuple[str, str]:
    """Возвращает (relative_text, bootstrap_color) для времени последней проверки."""
    if verified_at is None:
        return "не проверялось", "warning"
    delta = datetime.now() - verified_at
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return "только что", "success"
    if hours < 24:
        return f"{int(hours)} ч назад", "success"
    days = int(hours // 24)
    if days < 3:
        return f"{days} дн назад", "secondary"
    return f"{days} дн назад", "warning"


# ---------------------------------------------------------------------------
# Health check (без авторизации, для мониторинга)
# ---------------------------------------------------------------------------

@router.get("/healthz")
async def healthz() -> JSONResponse:
    """Liveness + DB connectivity. Используется nginx и внешним мониторингом."""
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return JSONResponse({"status": "ok"})
    except Exception as e:
        log.error("healthz_failed", error=str(e), exc_info=True)
        return JSONResponse({"status": "down", "error": str(e)}, status_code=503)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)  # type: ignore[return-value]
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    # Rate limit — защита от bruteforce пароля
    if not check_rate_limit(
        request,
        bucket="login",
        max_attempts=LOGIN_RATE_LIMIT_ATTEMPTS,
        window_sec=LOGIN_RATE_LIMIT_WINDOW_SEC,
    ):
        log.warning("login_rate_limited", ip=request.client.host if request.client else "?")
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Слишком много попыток, подождите минуту"},
            status_code=429,
        )

    if password == settings.admin_secret_key:
        resp = RedirectResponse("/", status_code=303)
        set_session(resp, authenticated=True)
        return resp
    return templates.TemplateResponse(  # type: ignore[return-value]
        "login.html", {"request": request, "error": "Неверный пароль"}
    )


@router.get("/logout")
async def logout() -> RedirectResponse:
    resp = RedirectResponse("/login", status_code=303)
    set_session(resp, authenticated=False)
    return resp


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, period: str = "week") -> HTMLResponse:
    if not is_authenticated(request):
        return _login_redirect()  # type: ignore[return-value]

    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.db.models.warehouse import Warehouse
    from app.services.cookie_service import get_active_cookie

    from app.services.app_state_service import get_state

    async with AsyncSessionLocal() as session:
        known_result = await session.execute(select(Warehouse.canonical_name))
        known: set[str] = set(known_result.scalars().all())
        cookie_row = await get_active_cookie(session)
        cookie_health = cookie_row.health if cookie_row else "unknown"
        cookie_updated = cookie_row.updated_at if cookie_row else None
        cookie_verified_at = cookie_row.last_verified_at if cookie_row else None
        bot_state = await get_state(session)
        # Детачим чтобы можно было читать поля после закрытия сессии
        bot_enabled = bot_state.bot_enabled
        poll_interval = bot_state.poll_interval_minutes
        last_success_at = bot_state.last_success_at
        last_success_processed = bot_state.last_success_processed
        last_error_at = bot_state.last_error_at
        last_error_text = bot_state.last_error_text

    verified_text, verified_color = _format_verified(cookie_verified_at)

    period = period if period in _PERIODS else "week"
    tasks = stats_module.get_tasks(known)
    s = stats_module.compute_stats(tasks, period)
    attention_count = sum(1 for t in tasks if t.needs_attention)

    csrf_token, is_new_csrf = get_csrf_token(request)
    resp = templates.TemplateResponse("dashboard.html", {
        "request": request,
        "period": period,
        "stats": s,
        "attention_count": attention_count,
        "cookie_health": cookie_health,
        "cookie_updated": cookie_updated,
        "cookie_verified_text": verified_text,
        "cookie_verified_color": verified_color,
        "dry_run": settings.wb_dry_run,
        "bot_enabled": bot_enabled,
        "poll_interval": poll_interval,
        "last_success_at": last_success_at,
        "last_success_processed": last_success_processed,
        "last_error_at": last_error_at,
        "last_error_text": last_error_text,
        "msg": request.query_params.get("msg", ""),
        "csrf_token": csrf_token,
    })
    if is_new_csrf:
        set_csrf_cookie(resp, csrf_token)
    return resp


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(
    request: Request,
    status: str = "",
    needs_attention: str = "",
) -> HTMLResponse:
    if not is_authenticated(request):
        return _login_redirect()  # type: ignore[return-value]

    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.db.models.warehouse import Warehouse
    from app.db.models.task import TaskStatus

    async with AsyncSessionLocal() as session:
        known_result = await session.execute(select(Warehouse.canonical_name))
        known: set[str] = set(known_result.scalars().all())

    all_tasks = stats_module.get_tasks(known)

    filtered = list(all_tasks)
    if status:
        filtered = [t for t in filtered if t.status == status]
    if needs_attention == "1":
        filtered = [t for t in filtered if t.needs_attention]

    # Показываем последние 300 строк (крупнейшие row_number = новее)
    displayed = sorted(filtered, key=lambda t: t.row_number, reverse=True)[:300]

    return templates.TemplateResponse("tasks.html", {
        "request": request,
        "tasks": displayed,
        "current_status": status,
        "needs_attention_filter": needs_attention == "1",
        "status_options": [s.value for s in TaskStatus],
        "total_filtered": len(filtered),
        "total_all": len(all_tasks),
    })  # tasks.html — read-only, CSRF не нужен


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    if not is_authenticated(request):
        return _login_redirect()  # type: ignore[return-value]

    from app.db.session import AsyncSessionLocal
    from app.services.app_state_service import get_state
    from app.services.cookie_service import get_active_cookie

    async with AsyncSessionLocal() as session:
        cookie_row = await get_active_cookie(session)
        cookie_health = cookie_row.health if cookie_row else "unknown"
        cookie_updated = cookie_row.updated_at if cookie_row else None
        cookie_verified_at = cookie_row.last_verified_at if cookie_row else None
        bot_state = await get_state(session)
        bot_enabled = bot_state.bot_enabled
        poll_interval = bot_state.poll_interval_minutes

    verified_text, verified_color = _format_verified(cookie_verified_at)

    csrf_token, is_new_csrf = get_csrf_token(request)
    resp = templates.TemplateResponse("settings.html", {
        "request": request,
        "cookie_health": cookie_health,
        "cookie_updated": cookie_updated,
        "cookie_verified_at": cookie_verified_at,
        "cookie_verified_text": verified_text,
        "cookie_verified_color": verified_color,
        "dry_run": settings.wb_dry_run,
        "bot_enabled": bot_enabled,
        "poll_interval": poll_interval,
        "msg": request.query_params.get("msg", ""),
        "csrf_token": csrf_token,
    })
    if is_new_csrf:
        set_csrf_cookie(resp, csrf_token)
    return resp


@router.post("/settings/cookie")
async def save_cookie(
    request: Request,
    cookie_str: str = Form(...),
    authorizev3: str = Form(...),
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _login_redirect()
    if not verify_csrf(request, csrf_token):
        return _forbidden_csrf()
    if not _check_action_limit(request):
        return _too_many_requests()

    from app.db.session import AsyncSessionLocal
    from app.services.cookie_service import save_cookie as svc_save

    async with AsyncSessionLocal() as session:
        await svc_save(session, cookie_str.strip(), {"authorizev3": authorizev3.strip()})

    log.info("cookie_updated_via_panel")
    return RedirectResponse("/settings?msg=Куки+сохранены", status_code=303)


@router.post("/settings/check-cookie")
async def check_cookie(
    request: Request,
    background_tasks: BackgroundTasks,
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _login_redirect()
    if not verify_csrf(request, csrf_token):
        return _forbidden_csrf()
    if not _check_action_limit(request):
        return _too_many_requests()

    background_tasks.add_task(_check_cookie_health)
    return RedirectResponse("/settings?msg=Проверка+запущена", status_code=303)


# ---------------------------------------------------------------------------
# Manual run
# ---------------------------------------------------------------------------

@router.post("/run")
async def run_now(
    request: Request,
    background_tasks: BackgroundTasks,
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _login_redirect()
    if not verify_csrf(request, csrf_token):
        return _forbidden_csrf()
    if not _check_action_limit(request):
        return _too_many_requests()

    background_tasks.add_task(_run_process_once)
    return RedirectResponse("/?msg=Обработка+запущена", status_code=303)


# ---------------------------------------------------------------------------
# Bot control: пауза / возобновление / смена интервала
# ---------------------------------------------------------------------------

@router.post("/bot/toggle")
async def bot_toggle(request: Request, csrf_token: str = Form(...)):
    if not is_authenticated(request):
        return _login_redirect()
    if not verify_csrf(request, csrf_token):
        return _forbidden_csrf()
    if not _check_action_limit(request):
        return _too_many_requests()

    from app.db.session import AsyncSessionLocal
    from app.services.app_state_service import get_state, set_bot_enabled

    async with AsyncSessionLocal() as session:
        state = await get_state(session)
        new_enabled = not state.bot_enabled
        await set_bot_enabled(session, new_enabled)

    msg = "Бот+возобновлён" if new_enabled else "Бот+остановлен"
    log.info("bot_toggled", enabled=new_enabled)
    return RedirectResponse(f"/?msg={msg}", status_code=303)


@router.post("/bot/clear-error")
async def clear_bot_error(request: Request, csrf_token: str = Form(...)):
    if not is_authenticated(request):
        return _login_redirect()
    if not verify_csrf(request, csrf_token):
        return _forbidden_csrf()
    if not _check_action_limit(request):
        return _too_many_requests()

    from app.db.session import AsyncSessionLocal
    from app.services.app_state_service import clear_last_error

    async with AsyncSessionLocal() as session:
        await clear_last_error(session)
    return RedirectResponse("/?msg=Ошибка+очищена", status_code=303)


@router.post("/sessions/revoke-all")
async def revoke_all_sessions(request: Request, csrf_token: str = Form(...)):
    """Инкрементирует session_version → все выпущенные admin-cookies инвалидны."""
    if not is_authenticated(request):
        return _login_redirect()
    if not verify_csrf(request, csrf_token):
        return _forbidden_csrf()
    if not _check_action_limit(request):
        return _too_many_requests()

    from app.db.session import AsyncSessionLocal
    from app.services.app_state_service import bump_session_version
    from app.web.auth import set_current_session_version

    async with AsyncSessionLocal() as session:
        new_version = await bump_session_version(session)
    # Сразу применяем — сам текущий юзер тоже слетит и попадёт на /login
    set_current_session_version(new_version)
    log.warning("all_sessions_revoked", new_version=new_version)
    return RedirectResponse("/login", status_code=303)


@router.post("/bot/interval")
async def bot_set_interval(
    request: Request,
    interval_minutes: int = Form(..., ge=1, le=60),
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _login_redirect()
    if not verify_csrf(request, csrf_token):
        return _forbidden_csrf()
    if not _check_action_limit(request):
        return _too_many_requests()

    from app.db.session import AsyncSessionLocal
    from app.services.app_state_service import set_poll_interval
    from app.scheduler.jobs import reschedule_poll

    async with AsyncSessionLocal() as session:
        await set_poll_interval(session, interval_minutes)
    reschedule_poll(interval_minutes)
    log.info("poll_interval_changed", minutes=interval_minutes)
    return RedirectResponse(f"/settings?msg=Интервал+{interval_minutes}+мин", status_code=303)


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def _run_process_once() -> None:
    from app.services.app_state_service import run_with_tracking
    from app.services.run_lock import release, try_acquire
    from app.services.task_processor import process_once

    # Тот же lock что и у scheduler — защита от concurrent запусков
    # (клик-спам «Запустить» и параллельный slot_rush).
    if not try_acquire():
        log.info("manual_run_skipped_already_running")
        return
    try:
        log.info("manual_run_start")
        await run_with_tracking(process_once, label="manual_run")
        stats_module.invalidate_cache()
        log.info("manual_run_done")
    finally:
        release()


async def _check_cookie_health() -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.cookie_service import check_cookie_health

    async with AsyncSessionLocal() as session:
        health = await check_cookie_health(session)
    log.info("cookie_health_checked", health=health)
