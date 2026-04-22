from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskDelivery(Base):
    """Трек доставки товара по отправленной заявке перераспределения.

    Создаётся после 200 OK от WB. Наблюдатель (delivery_watcher) периодически
    дергает stocks-report и сравнивает текущий qty на dst с baseline —
    так отличаем «заявку приняли» от «товар реально приехал».
    """
    __tablename__ = "task_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sheet_row: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    nm_id: Mapped[int] = mapped_column(BigInteger)
    chrt_id: Mapped[int] = mapped_column(BigInteger)
    dst_warehouse_id: Mapped[int] = mapped_column(Integer)
    expected_quantity: Mapped[int] = mapped_column(Integer)
    dst_qty_baseline: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
