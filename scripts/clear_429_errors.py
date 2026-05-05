"""Очистка строк с ошибкой 429 из таблицы заданий.

Находит все строки где в Коментарии упоминается «429» и сбрасывает:
- «Требует реакции» → пусто
- «Коментарий» → пусто

Статус не трогаем — IN_QUEUE остаётся, и бот сам переобработает
такие строки на следующем цикле уже с правильным handling 429.

Использование:
  py -m scripts.clear_429_errors           # dry-run, только список
  py -m scripts.clear_429_errors --apply   # реально записывает в таблицу
"""
import sys

from app.sheets import reader, writer

# Колонки 0-based в массиве (gspread)
COL_STATUS_IDX = 7        # H
COL_NEEDS_ATTENTION_IDX = 11  # L
COL_COMMENT_IDX = 12      # M


def main(apply: bool) -> None:
    print(f"Режим: {'APPLY' if apply else 'DRY-RUN'}")
    rows = reader.read_tasks_raw()
    print(f"Прочитано строк: {len(rows)}")

    candidates: list[tuple[int, str, str, str]] = []  # (row_num, status, attn, comment)
    for i, row in enumerate(rows, start=1):
        if i == 1:
            continue  # заголовок
        comment = row[COL_COMMENT_IDX] if len(row) > COL_COMMENT_IDX else ""
        if "429" not in comment:
            continue
        status = row[COL_STATUS_IDX] if len(row) > COL_STATUS_IDX else ""
        attn = row[COL_NEEDS_ATTENTION_IDX] if len(row) > COL_NEEDS_ATTENTION_IDX else ""
        candidates.append((i, status, attn, comment))

    print(f"\nНайдено строк с 429-ошибкой: {len(candidates)}")
    for row_num, status, attn, comment in candidates[:20]:
        print(f"  row={row_num}  status={status!r}  attn={attn!r}  comment={comment[:60]!r}")
    if len(candidates) > 20:
        print(f"  ... и ещё {len(candidates) - 20}")

    if not apply:
        print("\nDRY-RUN: ничего не записываем. Перезапусти с --apply.")
        return

    if not candidates:
        print("Нечего чистить.")
        return

    print(f"\nОчищаю {len(candidates)} строк...")
    for row_num, _, _, _ in candidates:
        writer.update_task_row(
            row_num,
            needs_attention=False,
            comment="",
        )
    writer.flush()
    print(f"Готово. Очищено {len(candidates)} строк.")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    main(apply)
