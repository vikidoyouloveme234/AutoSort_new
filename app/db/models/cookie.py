from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# WB session cookie — хранится зашифрованным через Fernet.
# Никогда не логировать поля encrypted_cookie и raw_headers.


class WbCookie(Base):
    __tablename__ = "wb_cookies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    encrypted_cookie: Mapped[str] = mapped_column(Text)   # Fernet-зашифрованные куки
    encrypted_headers: Mapped[str | None] = mapped_column(Text)  # AuthorizeV3, Wb-Seller-Lk
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    is_active: Mapped[bool] = mapped_column(default=True)
    # Статус проверки: "ok" / "expired" / "unknown"
    health: Mapped[str] = mapped_column(default="unknown")
    # Время последней успешной проверки сессии через refresh_seller_lk
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
