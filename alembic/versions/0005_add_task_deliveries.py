"""add task_deliveries

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_deliveries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sheet_row", sa.Integer, nullable=False, unique=True),
        sa.Column("nm_id", sa.BigInteger, nullable=False),
        sa.Column("chrt_id", sa.BigInteger, nullable=False),
        sa.Column("dst_warehouse_id", sa.Integer, nullable=False),
        sa.Column("expected_quantity", sa.Integer, nullable=False),
        sa.Column("dst_qty_baseline", sa.Integer, nullable=False),
        sa.Column("submitted_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_task_deliveries_sheet_row", "task_deliveries", ["sheet_row"])


def downgrade() -> None:
    op.drop_index("ix_task_deliveries_sheet_row", table_name="task_deliveries")
    op.drop_table("task_deliveries")
