"""Тесты буферизации writer.py: накопление и flush."""
from unittest.mock import MagicMock, patch

import pytest

from app.sheets import writer


@pytest.fixture(autouse=True)
def _clear_writer_state():
    """Чистим буфер перед каждым тестом."""
    writer._pending.clear()
    yield
    writer._pending.clear()


@pytest.fixture
def mock_ws():
    """Мокаем worksheet и пропускаем rate-limiter + retry."""
    ws = MagicMock()
    with (
        patch("app.sheets.writer.get_sheet", return_value=ws),
        patch("app.sheets.writer.acquire_write"),
        patch("app.sheets.writer.with_retry", side_effect=lambda label, op: op()),
    ):
        yield ws


def test_single_update_below_threshold_buffers_only(mock_ws) -> None:
    """1 строка < 10 — в Sheets ничего не уходит, всё в буфере."""
    writer.update_task_row(5, status="ОК", comment="hi")
    assert mock_ws.update_cells.call_count == 0
    assert len(writer._pending) == 2  # 2 столбца


def test_flush_sends_all_buffered_cells(mock_ws) -> None:
    """flush() отправляет всё что накопилось одной call'ой."""
    writer.update_task_row(5, status="A")
    writer.update_task_row(6, comment="B")
    writer.update_task_row(7, needs_attention=True)
    writer.flush()

    assert mock_ws.update_cells.call_count == 1
    cells = mock_ws.update_cells.call_args[0][0]
    assert len(cells) == 3


def test_auto_flush_at_threshold(mock_ws) -> None:
    """Когда буфер набирает 10 уникальных строк — авто-flush."""
    for row in range(1, 10):  # 9 строк — пока без flush'а
        writer.update_task_row(row, status="A")
    assert mock_ws.update_cells.call_count == 0

    writer.update_task_row(10, status="A")  # 10-я строка → triggers flush
    assert mock_ws.update_cells.call_count == 1
    assert len(writer._pending) == 0  # буфер очищен


def test_dedup_same_cell_last_wins(mock_ws) -> None:
    """Две записи в (row=5, col=STATUS) — побеждает последняя."""
    writer.update_task_row(5, status="FIRST")
    writer.update_task_row(5, status="SECOND")
    writer.flush()

    cells = mock_ws.update_cells.call_args[0][0]
    status_cells = [c for c in cells if c.col == writer.COL_STATUS]
    assert len(status_cells) == 1
    assert status_cells[0].value == "SECOND"


def test_flush_on_empty_buffer_is_noop(mock_ws) -> None:
    """flush без накоплений — не делает API call."""
    writer.flush()
    assert mock_ws.update_cells.call_count == 0


def test_no_args_does_not_buffer(mock_ws) -> None:
    """update_task_row без полей — ничего не стейджит."""
    writer.update_task_row(5)
    assert len(writer._pending) == 0


def test_buffer_cleared_before_api_call(mock_ws) -> None:
    """Буфер очищается ДО API call — если call упадёт, не будет повтора того же."""
    seen_pending_at_call: list[int] = []

    def fake_update(*args, **kwargs):
        seen_pending_at_call.append(len(writer._pending))

    mock_ws.update_cells = fake_update

    writer.update_task_row(1, status="A")
    writer.flush()
    assert seen_pending_at_call == [0]
