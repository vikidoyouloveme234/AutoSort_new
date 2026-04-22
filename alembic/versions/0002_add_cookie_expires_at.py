"""add expires_at to wb_cookies

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wb_cookies",
        sa.Column("expires_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wb_cookies", "expires_at")
