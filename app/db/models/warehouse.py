from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Canonical warehouse names from the "Склады" sheet.
# wb_warehouse_id — заполняется один раз скриптом через WB API (нужен API-ключ).
# aliases — через запятую, напр. "СПБ" для "Склад Шушары".


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(200), unique=True)
    wb_warehouse_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    aliases: Mapped[str | None] = mapped_column(String(500))  # comma-separated

    def alias_list(self) -> list[str]:
        if not self.aliases:
            return []
        return [a.strip() for a in self.aliases.split(",") if a.strip()]
