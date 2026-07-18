import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    strategy_id: Mapped[str] = mapped_column(String, ForeignKey("strategies.id"), index=True)
    exchange_key_id: Mapped[str] = mapped_column(String, ForeignKey("exchange_keys.id"), index=True)

    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="idle")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
