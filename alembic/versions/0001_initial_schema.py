"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("canonical_name", sa.String(200), nullable=False, unique=True),
        sa.Column("wb_warehouse_id", sa.Integer, unique=True, nullable=True),
        sa.Column("aliases", sa.String(500), nullable=True),
    )

    op.create_table(
        "articles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(300), nullable=False, unique=True),
        sa.Column("nm_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("chrt_id", sa.BigInteger, nullable=True),
    )

    op.create_table(
        "wb_cookies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("encrypted_cookie", sa.Text, nullable=False),
        sa.Column("encrypted_headers", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("health", sa.String(20), nullable=False, server_default="unknown"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("article", sa.String(200), nullable=False),
        sa.Column("responsible", sa.String(100), nullable=False),
        sa.Column("date_added", sa.Date, nullable=True),
        sa.Column("nm_id", sa.Integer, nullable=True),
        sa.Column("warehouse_src", sa.String(200), nullable=False),
        sa.Column("warehouse_dst", sa.String(200), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("date_done", sa.Date, nullable=True),
        sa.Column("deadline", sa.Date, nullable=True),
        sa.Column("needs_attention", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("sheet_row", sa.Integer, nullable=True),
        sa.Column("chrt_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_sheet_row", "tasks", ["sheet_row"])


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("wb_cookies")
    op.drop_table("articles")
    op.drop_table("warehouses")
