import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Numeric, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String, index=True)
    timeframe: Mapped[str] = mapped_column(String)

    risk_percent: Mapped[float] = mapped_column(Numeric(10, 4))
    take_profit_percent: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    stop_loss_percent: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)

    is_ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[dict] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
