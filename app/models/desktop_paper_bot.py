"""Paper-only bot configuration, separate from exchange-connected bots."""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Numeric, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class DesktopPaperBot(Base):
    __tablename__ = "nexora_desktop_paper_bots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(String, ForeignKey("strategies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    allocated_cash: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    risk_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String, default="configured", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
