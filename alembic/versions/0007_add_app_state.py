"""add app_state singleton table

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("bot_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("poll_interval_minutes", sa.Integer, nullable=False, server_default="5"),
        sa.Column("last_success_at", sa.DateTime, nullable=True),
        sa.Column("last_success_processed", sa.Integer, nullable=True),
        sa.Column("last_error_at", sa.DateTime, nullable=True),
        sa.Column("last_error_text", sa.Text, nullable=True),
    )
    # Сидим singleton-строку id=1
    op.execute("INSERT INTO app_state (id, bot_enabled, poll_interval_minutes) VALUES (1, true, 5)")


def downgrade() -> None:
    op.drop_table("app_state")
