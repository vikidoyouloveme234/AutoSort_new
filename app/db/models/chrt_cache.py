"""Кэш chrtID по nmID — fallback когда /stocks сдох по 429 или сети.

chrtID (ID карточки-вариации) почти не меняется у WB — только при смене
категории товара. Храним последнее известное значение, чтобы бот мог
подать заявку даже если /stocks временно недоступен. Baseline в таком
fallback-сценарии = 0 (watcher будет чуть менее точен — фиксирует DONE
при любом приходе на dst, а не только на ≥expected_quantity).
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChrtCache(Base):
    __tablename__ = "chrt_cache"

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chrt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )
