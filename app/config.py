import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Фикс Windows: psycopg2/libpq читает конфиги системного PostgreSQL в Windows-1251
if sys.platform == "win32":
    os.environ.setdefault("PGSYSCONFDIR", str(Path.home()))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str

    # Google Sheets
    google_sheet_id: str
    google_service_account_file: str = "secrets/google_sa.json"

    # WB Official API
    wb_api_key: str = ""

    # WB Unofficial API encryption
    fernet_key: str

    # App behaviour
    wb_dry_run: bool = True
    log_level: str = "INFO"

    # Admin panel
    admin_secret_key: str = "change_me"
    # В прод ставить True (HTTPS). В dev (http://localhost) — False, иначе куки не прилетят.
    session_cookie_secure: bool = False


settings = Settings()  # type: ignore[call-arg]
