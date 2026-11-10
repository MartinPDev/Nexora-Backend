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
