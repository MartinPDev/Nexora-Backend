"""Authenticated, user-scoped desktop read API.

Only expose values supported by the existing database; no simulated balances
or fabricated trade history are returned.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.bot import Bot
from app.models.strategy import Strategy
from app.models.rapid_scalper_trade import RapidScalperTrade
from app.models.paper_wallet import PaperWallet
from app.models.desktop_paper_bot import DesktopPaperBot
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
from pydantic import BaseModel, Field

router = APIRouter(tags=["desktop"])


@router.get("/health")
def desktop_health():
    return {"status": "ok", "mode": "paper", "version": "beta"}


@router.get("/desktop/bots")
def desktop_bots(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bots = db.query(DesktopPaperBot).filter(
        DesktopPaperBot.user_id == current_user.id
    ).all()
    return {"bots": [
        {
            "id": bot.id,
            "name": bot.name,
            "symbol": bot.symbol,
            "timeframe": bot.timeframe,
            "allocated_cash": float(bot.allocated_cash),
            "risk_percent": float(bot.risk_percent),
            "status": bot.status,
            "is_enabled": False,
            "strategy_id": bot.strategy_id,
            "mode": "paper",
        }
        for bot in bots
    ]}


@router.get("/desktop/strategies")
def desktop_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strategies = db.query(Strategy).filter(Strategy.user_id == current_user.id).all()
    return {"strategies": [
        {
            "id": item.id,
            "name": item.name,
            "symbol": item.symbol,
            "timeframe": item.timeframe,
            "risk_percent": float(item.risk_percent),
            "take_profit_percent": (
                float(item.take_profit_percent)
                if item.take_profit_percent is not None else None
            ),
            "stop_loss_percent": (
                float(item.stop_loss_percent)
                if item.stop_loss_percent is not None else None
            ),
            "is_ai_enabled": item.is_ai_enabled,
        }
        for item in strategies
    ]}


@router.get("/desktop/dashboard")
def desktop_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Account-scoped bot overview; financial metrics require a real paper ledger."""
    bots = db.query(Bot).filter(Bot.user_id == current_user.id).all()
    wallet = db.query(PaperWallet).filter(
        PaperWallet.user_id == current_user.id
    ).first()
    return {
        "bots_total": len(bots),
        "bots_running": sum(bool(bot.is_enabled) for bot in bots),
        # Cash is a verified wallet field; portfolio equity also requires
        # positions and must not be inferred from cash alone.
        "paper_cash": float(wallet.cash_balance) if wallet else None,
        "portfolio_value": None,
        "daily_pnl": None,
        "daily_pnl_percent": None,
        "weekly_pnl": None,
        "open_positions": None,
        "signals_today": None,
        "win_rate": None,
        "closed_trades": None,
        "chart": [],
        "trades": [],
        "positions": [],
        "activity": [],
        "financial_data_status": "unavailable",
        "mode": "paper",
    }


@router.get("/desktop/portfolio")
def desktop_portfolio(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist a one-time $1,000 simulated cash wallet per account.

    This is cash only. No positions, P&L or performance history are inferred.
    The schema must be created by the explicit paper-wallet migration first.
    """
    wallet = db.query(PaperWallet).filter(
        PaperWallet.user_id == current_user.id
    ).first()
    if wallet is None:
        # Savepoint handles simultaneous first requests without rolling back
        # the caller's surrounding transaction.
        try:
            with db.begin_nested():
                db.add(PaperWallet(
                    user_id=current_user.id,
                    initial_balance=Decimal("1000.00"),
                    cash_balance=Decimal("1000.00"),
                    currency="USD",
                ))
                db.flush()
        except IntegrityError:
            pass
        wallet = db.query(PaperWallet).filter(
            PaperWallet.user_id == current_user.id
        ).first()
        if wallet is None:
            raise RuntimeError("Paper wallet initialization failed.")
        db.commit()
    return {
        "total_value": float(wallet.cash_balance),
        "cash": float(wallet.cash_balance),
        "currency": wallet.currency,
        "unrealized_pnl": None,
        "return_percent": None,
        "positions": [],
        "history": [],
        "financial_data_status": "cash_only",
    }


@router.get("/desktop/trades")
def desktop_trades(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Only persisted, closed paper scalper trades owned by this username."""
    rows = (
        db.query(RapidScalperTrade)
        .filter(
            RapidScalperTrade.username == current_user.username,
            RapidScalperTrade.mode == "paper",
            RapidScalperTrade.closed_at.isnot(None),
        )
        .order_by(RapidScalperTrade.closed_at.desc())
        .limit(200)
        .all()
    )
    return {
        "trades": [
            {
                "id": row.id,
                "symbol": row.symbol,
                "side": row.side,
                "amount": row.amount_usd,
                "price": row.exit_price,
                "pnl": row.pnl_usd,
                "time": row.closed_at.isoformat() if row.closed_at else None,
                "source": "rapid_scalper_paper",
            }
            for row in rows
        ],
        "data_status": "rapid_scalper_only",
    }


@router.get("/desktop/notifications")
def desktop_notifications(current_user: User = Depends(get_current_user)):
    """No notification records are claimed without a backed notification store."""
    return {"notifications": [], "data_status": "unavailable"}


@router.get("/desktop/markets")
def desktop_markets(current_user: User = Depends(get_current_user)):
    """Fail explicitly until a vetted Kraken public market-data feed is connected."""
    return {"markets": [], "data_status": "unavailable"}


class DesktopPaperBotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    strategy_id: str
    symbol: str
    timeframe: str
    allocated_cash: Decimal = Field(gt=0, le=1000)
    risk_percent: Decimal = Field(gt=0, le=10)


@router.post("/desktop/bots", status_code=201)
def create_desktop_paper_bot(
    payload: DesktopPaperBotCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Configure an inert paper bot, never a live exchange bot."""
    strategy = db.query(Strategy).filter(
        Strategy.id == payload.strategy_id,
        Strategy.user_id == current_user.id,
    ).first()
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    if payload.symbol != strategy.symbol or payload.timeframe != strategy.timeframe:
        raise HTTPException(status_code=422, detail="Bot market and timeframe must match its strategy.")
    # Serialize allocation decisions per wallet on databases supporting
    # SELECT FOR UPDATE (PostgreSQL). SQLite does not provide row locks.
    wallet = db.query(PaperWallet).filter(
        PaperWallet.user_id == current_user.id
    ).with_for_update().first()
    if wallet is None:
        raise HTTPException(status_code=409, detail="Initialize your paper wallet in Portfolio first.")
    existing = db.query(DesktopPaperBot).filter(
        DesktopPaperBot.user_id == current_user.id
    ).all()
    reserved = sum((Decimal(str(bot.allocated_cash)) for bot in existing), Decimal("0"))
    if reserved + payload.allocated_cash > Decimal(str(wallet.cash_balance)):
        raise HTTPException(status_code=409, detail="Insufficient unallocated paper cash.")
    row = DesktopPaperBot(
        user_id=current_user.id,
        strategy_id=strategy.id,
        name=payload.name,
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        allocated_cash=payload.allocated_cash,
        risk_percent=payload.risk_percent,
        is_enabled=False,
        status="configured",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "name": row.name,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "strategy_id": row.strategy_id,
        "allocated_cash": float(row.allocated_cash),
        "risk_percent": float(row.risk_percent),
        "status": row.status,
        "is_enabled": False,
        "mode": "paper",
    }
