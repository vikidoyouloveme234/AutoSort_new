"""Печатает уникальные значения комментариев в таблице — диагностика."""
from collections import Counter

from app.sheets import reader

COL_COMMENT_IDX = 12
COL_NEEDS_ATTENTION_IDX = 11

rows = reader.read_tasks_raw()
print(f"Total rows: {len(rows)}")

comments = Counter()
attn_yes_count = 0
for row in rows[1:]:
    comment = row[COL_COMMENT_IDX] if len(row) > COL_COMMENT_IDX else ""
    attn = row[COL_NEEDS_ATTENTION_IDX] if len(row) > COL_NEEDS_ATTENTION_IDX else ""
    if comment:
        # Берём первые 60 символов как ключ группировки
        comments[comment[:60]] += 1
    if attn == "Да":
        attn_yes_count += 1

print(f"\nRows with needs_attention='Да': {attn_yes_count}")
print(f"\nTop 15 unique comment patterns:")
for c, count in comments.most_common(15):
    print(f"  [{count:>4}] {c!r}")
