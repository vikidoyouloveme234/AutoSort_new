from datetime import date
from enum import StrEnum

from sqlalchemy import Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskStatus(StrEnum):
    CREATED = "Создан"
    IN_QUEUE = "В очереди бота"
    DONE_BOT = "Выполнен ботом"
    DONE_MANUAL = "Выполнен вручную"
    DONE_PARTIAL = "Перемещено 90%+"
    CANCELLED = "Отменен по дедлайну"

    @classmethod
    def final_statuses(cls) -> set["TaskStatus"]:
        return {cls.DONE_BOT, cls.DONE_MANUAL, cls.DONE_PARTIAL}


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Columns from Google Sheet (A–M)
    article: Mapped[str] = mapped_column(String(200))           # A: Артикул
    responsible: Mapped[str] = mapped_column(String(100))       # B: Ответственный
    date_added: Mapped[date | None] = mapped_column(Date)       # C: Дата добавления
    nm_id: Mapped[int | None] = mapped_column(Integer)          # D: Артикул ВБ (nmID)
    warehouse_src: Mapped[str] = mapped_column(String(200))     # E: Склад отгрузки
    warehouse_dst: Mapped[str | None] = mapped_column(String(200))  # F: Склад получения
    quantity: Mapped[int | None] = mapped_column(Integer)       # G: Кол-во
    status: Mapped[str] = mapped_column(String(50))             # H: Статус
    date_done: Mapped[date | None] = mapped_column(Date)        # I: Дата выполнения (бот)
    deadline: Mapped[date | None] = mapped_column(Date)         # J: Дедлайн на отмену
    # K — формула в таблице, бот не трогает
    needs_attention: Mapped[bool] = mapped_column(default=False)  # L: Требует реакции
    comment: Mapped[str | None] = mapped_column(Text)           # M: Коментарий

    # Internal fields
    sheet_row: Mapped[int | None] = mapped_column(Integer)      # Номер строки в Sheets (для обновления)
    chrt_id: Mapped[int | None] = mapped_column(Integer)        # Кэш chrtID из WB Content API
