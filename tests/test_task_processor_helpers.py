"""Тесты на детекторы кодов WB-ошибок в task_processor."""
from app.services.task_processor import _is_already_in_process, _quota_exceeded_side
from app.wb_client.client import OrderResponse


def _resp(status: int, body: dict) -> OrderResponse:
    return OrderResponse(success=False, status_code=status, body=body)


# ---------- _is_already_in_process ----------

def test_already_in_process_400_detected() -> None:
    """Реальный ответ от WB 2026-04-18: HTTP 400 + errorText."""
    body = {"data": None, "error": True, "errorText": "requestAlreadyInProcess"}
    assert _is_already_in_process(_resp(400, body)) is True


def test_already_in_process_200_with_body_error_detected() -> None:
    """WB иногда отдаёт 200 + body.error. Детектор не привязан к HTTP-коду."""
    body = {"data": None, "error": True, "errorText": "requestAlreadyInProcess"}
    assert _is_already_in_process(_resp(200, body)) is True


def test_already_in_process_other_error_text() -> None:
    body = {"error": True, "errorText": "nmError"}
    assert _is_already_in_process(_resp(400, body)) is False


def test_already_in_process_no_body() -> None:
    assert _is_already_in_process(_resp(500, {})) is False


# ---------- _quota_exceeded_side ----------

def test_quota_exceeded_src_side() -> None:
    """Реальный ответ от WB 2026-04-18 для Электростали как src."""
    body = {
        "data": None,
        "error": True,
        "errorText": "exceeded-quota",
        "additionalErrors": {"placement": ["srcOffice"]},
    }
    assert _quota_exceeded_side(_resp(400, body)) == "src"


def test_quota_exceeded_dst_side() -> None:
    body = {
        "error": True,
        "errorText": "exceeded-quota",
        "additionalErrors": {"placement": ["dstOffice"]},
    }
    assert _quota_exceeded_side(_resp(400, body)) == "dst"


def test_quota_exceeded_no_placement() -> None:
    """exceeded-quota без указания placement → None (не понимаем какой склад)."""
    body = {"error": True, "errorText": "exceeded-quota"}
    assert _quota_exceeded_side(_resp(400, body)) is None


def test_quota_exceeded_other_error_text() -> None:
    body = {"error": True, "errorText": "requestAlreadyInProcess"}
    assert _quota_exceeded_side(_resp(400, body)) is None


def test_quota_exceeded_additional_errors_none() -> None:
    """additionalErrors == None (а не пустой dict) — не должен крашить."""
    body = {"error": True, "errorText": "exceeded-quota", "additionalErrors": None}
    assert _quota_exceeded_side(_resp(400, body)) is None
