"""add last_verified_at to wb_cookies

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wb_cookies",
        sa.Column("last_verified_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wb_cookies", "last_verified_at")
