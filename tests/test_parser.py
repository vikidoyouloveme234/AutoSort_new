"""Тесты парсера строк листа «Задания»."""
from datetime import date

from app.sheets.parser import normalize_warehouse, parse_date, parse_tasks


# Helper для построения строк нужной длины с дефолтами
def _row(
    article="art1", responsible="Manager", date_added="01.01.26",
    nm_id="123", src="Коледино", dst="Электросталь", qty="1",
    status="Создан", date_done="", deadline="",
    formula_K="", needs_attention="", comment="",
):
    return [article, responsible, date_added, nm_id, src, dst, qty,
            status, date_done, deadline, formula_K, needs_attention, comment]


# ---------------------------------------------------------------------------
# normalize_warehouse
# ---------------------------------------------------------------------------

def test_alias_spb() -> None:
    assert normalize_warehouse("СПБ") == "Склад Шушары"


def test_alias_spb_lowercase() -> None:
    assert normalize_warehouse("спб") == "Склад Шушары"


def test_alias_ekb() -> None:
    assert normalize_warehouse("Екатеринбург") == "Екатеринбург - Перспективная 14"


def test_alias_novosemeyikno() -> None:
    assert normalize_warehouse("Новосемейкино") == "Самара (Новосемейкино)"


def test_alias_novosibirsk() -> None:
    assert normalize_warehouse("Новосиб") == "Новосибирск"


def test_alias_ryazan() -> None:
    assert normalize_warehouse("Рязань") == "Рязань (Тюшевское)"


def test_canonical_passthrough() -> None:
    assert normalize_warehouse("Коледино") == "Коледино"


def test_empty_warehouse_returns_none() -> None:
    assert normalize_warehouse("") is None
    assert normalize_warehouse("   ") is None


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------

def test_parse_date_yy_format() -> None:
    assert parse_date("09.02.26") == date(2026, 2, 9)


def test_parse_date_yyyy_format() -> None:
    assert parse_date("09.02.2026") == date(2026, 2, 9)


def test_parse_date_empty_returns_none() -> None:
    assert parse_date("") is None
    assert parse_date("   ") is None


def test_parse_date_invalid_returns_none() -> None:
    assert parse_date("не-дата") is None
    assert parse_date("2026-02-09") is None  # ISO format не поддерживается


# ---------------------------------------------------------------------------
# parse_tasks — пропуски
# ---------------------------------------------------------------------------

def test_parse_skips_empty_dst(known_warehouses: set[str]) -> None:
    rows = [["unik_korz", "Иванов", "09.02.26", "177047390", "Коледино", "", "10", "Создан", "", "", "", "", ""]]
    tasks, skipped = parse_tasks(rows, known_warehouses)
    assert len(tasks) == 0
    assert len(skipped) == 1
    assert skipped[0].needs_attention is True


def test_parse_unknown_warehouse_skipped(known_warehouses: set[str]) -> None:
    rows = [["unik_korz", "Иванов", "09.02.26", "177047390", "Коледино", "НеизвестныйСклад", "10", "Создан", "", "", "", "", ""]]
    tasks, skipped = parse_tasks(rows, known_warehouses)
    assert len(tasks) == 0
    assert "НеизвестныйСклад" in skipped[0].reason


# ---------------------------------------------------------------------------
# parse_tasks — корректный парсинг
# ---------------------------------------------------------------------------

def test_parse_alias_resolved(known_warehouses: set[str]) -> None:
    rows = [["unik_korz", "Иванов", "09.02.26", "177047390", "Коледино", "СПБ", "10", "Создан", "", "", "", "", ""]]
    tasks, skipped = parse_tasks(rows, known_warehouses)
    assert len(tasks) == 1
    assert tasks[0].warehouse_dst == "Склад Шушары"


def test_row_numbering_starts_at_2(known_warehouses: set[str]) -> None:
    """Строка 1 — заголовок (не передаётся), первая строка данных → row_number=2."""
    rows = [["art", "resp", "", "", "Коледино", "Краснодар", "5", "Создан", "", "", "", "", ""]]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].row_number == 2


def test_strip_whitespace_in_fields(known_warehouses: set[str]) -> None:
    rows = [["  art  ", "  resp  ", "", "", "Коледино", "  Краснодар  ", "5", "  Создан  ", "", "", "", "", ""]]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].article == "art"
    assert tasks[0].responsible == "resp"
    assert tasks[0].status == "Создан"


def test_nm_id_parsed_as_int(known_warehouses: set[str]) -> None:
    rows = [["art", "", "", "177047390", "Коледино", "Краснодар", "10", "Создан", "", "", "", "", ""]]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].nm_id == 177047390


def test_nm_id_empty_is_none(known_warehouses: set[str]) -> None:
    rows = [["art", "", "", "", "Коледино", "Краснодар", "10", "Создан", "", "", "", "", ""]]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].nm_id is None


def test_nm_id_invalid_string_is_none(known_warehouses: set[str]) -> None:
    rows = [["art", "", "", "не-число", "Коледино", "Краснодар", "10", "Создан", "", "", "", "", ""]]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].nm_id is None


def test_quantity_parsed(known_warehouses: set[str]) -> None:
    rows = [["art", "", "", "", "Коледино", "Краснодар", "700", "Создан", "", "", "", "", ""]]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].quantity == 700


def test_quantity_empty_is_none(known_warehouses: set[str]) -> None:
    rows = [["art", "", "", "", "Коледино", "Краснодар", "", "Создан", "", "", "", "", ""]]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].quantity is None


def test_deadline_parsed(known_warehouses: set[str]) -> None:
    rows = [["art", "", "", "", "Коледино", "Краснодар", "5", "Создан", "", "16.02.26", "", "", ""]]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].deadline == date(2026, 2, 16)


def test_needs_attention_da_parsed_as_true(known_warehouses: set[str]) -> None:
    """Колонка L «Да» → needs_attention=True."""
    rows = [_row(needs_attention="Да", comment="Ошибка WB 400")]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].needs_attention is True
    assert tasks[0].comment == "Ошибка WB 400"


def test_needs_attention_empty_is_false(known_warehouses: set[str]) -> None:
    """Колонка L пустая → needs_attention=False."""
    rows = [_row(needs_attention="", comment="")]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].needs_attention is False
    assert tasks[0].comment == ""


def test_needs_attention_case_insensitive(known_warehouses: set[str]) -> None:
    """«ДА» / «да» / «Да» — все True."""
    for value in ("ДА", "да", "Да"):
        rows = [_row(needs_attention=value)]
        tasks, _ = parse_tasks(rows, known_warehouses)
        assert tasks[0].needs_attention is True, f"failed for value={value!r}"


def test_needs_attention_garbage_is_false(known_warehouses: set[str]) -> None:
    """Любое значение кроме «да» (с любым регистром) → False."""
    for value in ("нет", "yes", "1", "true", "?"):
        rows = [_row(needs_attention=value)]
        tasks, _ = parse_tasks(rows, known_warehouses)
        assert tasks[0].needs_attention is False, f"failed for value={value!r}"


def test_comment_stripped(known_warehouses: set[str]) -> None:
    """Лишние пробелы в комментарии срезаются."""
    rows = [_row(comment="  Квота исчерпана  ")]
    tasks, _ = parse_tasks(rows, known_warehouses)
    assert tasks[0].comment == "Квота исчерпана"


def test_short_row_no_attention_no_comment(known_warehouses: set[str]) -> None:
    """Если в строке меньше 13 колонок — defaults: needs_attention=False, comment=''."""
    short_row = ["art1", "resp", "", "111", "Коледино", "Краснодар", "5", "Создан"]
    tasks, _ = parse_tasks([short_row], known_warehouses)
    assert tasks[0].needs_attention is False
    assert tasks[0].comment == ""


def test_mixed_rows_tasks_and_skipped(known_warehouses: set[str]) -> None:
    """Несколько строк: одна пропускается, две проходят — счётчики и row_number корректны."""
    rows = [
        ["art1", "resp", "", "111", "Коледино", "Краснодар", "5", "Создан", "", "", "", "", ""],
        ["art2", "resp", "", "222", "Коледино", "", "5", "Создан", "", "", "", "", ""],   # пустой dst → skip
        ["art3", "resp", "", "333", "Коледино", "Краснодар", "5", "Создан", "", "", "", "", ""],
    ]
    tasks, skipped = parse_tasks(rows, known_warehouses)
    assert len(tasks) == 2
    assert len(skipped) == 1
    assert skipped[0].row_number == 3   # заголовок=1, art1=2, art2=3
    assert tasks[0].row_number == 2
    assert tasks[1].row_number == 4
