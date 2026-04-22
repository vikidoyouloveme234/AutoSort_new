from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppState(Base):
    """Singleton-таблица с состоянием бота: пауза/работа, интервал опроса,
    время последнего успешного/ошибочного цикла. Всегда одна строка с id=1.
    """
    __tablename__ = "app_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Счётчик «поколения сессий» админки. Повышение revoke'ит все выпущенные
    # admin-сессии (полезно при утечке cookie или уходе менеджера).
    session_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
