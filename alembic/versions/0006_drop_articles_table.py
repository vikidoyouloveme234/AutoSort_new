"""drop articles table — chrtID кэш больше не нужен (берётся из LK /stocks)

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("articles")


def downgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(300), nullable=False, unique=True),
        sa.Column("nm_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("chrt_id", sa.BigInteger, nullable=True),
    )
