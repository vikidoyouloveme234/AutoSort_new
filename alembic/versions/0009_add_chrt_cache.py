"""add chrt_cache

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chrt_cache",
        sa.Column("nm_id", sa.BigInteger, primary_key=True),
        sa.Column("chrt_id", sa.BigInteger, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("chrt_cache")
