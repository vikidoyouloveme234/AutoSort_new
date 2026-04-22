"""drop expires_at from wb_cookies

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-16
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("wb_cookies", "expires_at")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column("wb_cookies", sa.Column("expires_at", sa.DateTime, nullable=True))
