import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from alembic import context
from sqlalchemy import engine_from_config, pool

load_dotenv(Path(__file__).parent.parent / ".env")

# Фикс для Windows: psycopg2/libpq пытается читать конфиги PostgreSQL 17
# в кодировке Windows-1251, что ломает UTF-8 декодирование
import sys
if sys.platform == "win32":
    os.environ.setdefault("PGSYSCONFDIR", str(Path.home()))

from app.db.base import Base
import app.db.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Для миграций используем синхронный psycopg2 (asyncpg нестабилен на Windows)
# В проде app использует asyncpg — это только для alembic
db_url = os.environ["DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
