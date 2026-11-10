"""Authenticated, user-scoped desktop read API.

Only expose values supported by the existing database; no simulated balances
or fabricated trade history are returned.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.bot import Bot
from app.models.strategy import Strategy
from app.models.rapid_scalper_trade import RapidScalperTrade

router = APIRouter(tags=["desktop"])


@router.get("/health")
def desktop_health():
    return {"status": "ok", "mode": "paper", "version": "beta"}


@router.get("/desktop/bots")
def desktop_bots(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bots = db.query(Bot).filter(Bot.user_id == current_user.id).all()
    return {"bots": [
        {
            "id": bot.id,
            "name": bot.name,
            "status": bot.status,
            "is_enabled": bot.is_enabled,
            "strategy_id": bot.strategy_id,
            "last_run_at": bot.last_run_at.isoformat() if bot.last_run_at else None,
            "last_error": bot.last_error,
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
    return {
        "bots_total": len(bots),
        "bots_running": sum(bool(bot.is_enabled) for bot in bots),
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
def desktop_portfolio(current_user: User = Depends(get_current_user)):
    """Do not imply that an unintegrated paper ledger has zero funds."""
    return {
        "total_value": None,
        "cash": None,
        "unrealized_pnl": None,
        "return_percent": None,
        "positions": [],
        "history": [],
        "financial_data_status": "unavailable",
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
