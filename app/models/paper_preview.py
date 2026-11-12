"""Durable, owner-scoped paper-preview records. No exchange execution."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Numeric, String, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def uid():
    return str(uuid.uuid4())


class PaperPreviewEnrollment(Base):
    __tablename__ = "nexora_preview_enrollments"
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("nexora_desktop_paper_bots.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    observer_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_action: Mapped[str] = mapped_column(String(20), nullable=True)
    last_reason: Mapped[str] = mapped_column(Text, nullable=True)
    last_scanned_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PaperPreviewProposal(Base):
    __tablename__ = "nexora_preview_proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("nexora_desktop_paper_bots.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    candle_timestamp: Mapped[int] = mapped_column(Numeric(20, 0), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(24, 12), nullable=False)
    principal: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    fee: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("bot_id", "candle_timestamp", name="uq_preview_bot_candle"),)


class PaperPreviewPosition(Base):
    __tablename__ = "nexora_preview_positions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("nexora_desktop_paper_bots.id"), nullable=False, index=True)
    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("nexora_preview_proposals.id"), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(24, 12), nullable=False)
    principal: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    entry_fee: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    peak_price: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[float] = mapped_column(Numeric(24, 10), nullable=True)
    exit_fee: Mapped[float] = mapped_column(Numeric(18, 8), nullable=True)
    pnl: Mapped[float] = mapped_column(Numeric(18, 8), nullable=True)
    exit_reason: Mapped[str] = mapped_column(String, nullable=True)
