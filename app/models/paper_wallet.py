"""Nexora-only paper wallet. No exchange keys or real-money balances."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class PaperWallet(Base):
    __tablename__ = "nexora_paper_wallets"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), primary_key=True
    )
    initial_balance: Mapped[float] = mapped_column(
        Numeric(18, 8), nullable=False
    )
    cash_balance: Mapped[float] = mapped_column(
        Numeric(18, 8), nullable=False
    )
    currency: Mapped[str] = mapped_column(String, default="USD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
