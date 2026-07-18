from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.bot import Bot
from app.models.strategy import Strategy
from app.models.exchange_key import ExchangeKey
from app.schemas.bot import BotCreate, BotToggle, BotOut

router = APIRouter(prefix="/bots", tags=["bots"])


@router.post("", response_model=BotOut)
def create_bot(
    payload: BotCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strategy = db.query(Strategy).filter(
        Strategy.id == payload.strategy_id,
        Strategy.user_id == current_user.id,
    ).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    exchange_key = db.query(ExchangeKey).filter(
        ExchangeKey.id == payload.exchange_key_id,
        ExchangeKey.user_id == current_user.id,
    ).first()
    if not exchange_key:
        raise HTTPException(status_code=404, detail="Exchange key not found")

    row = Bot(
        user_id=current_user.id,
        strategy_id=payload.strategy_id,
        exchange_key_id=payload.exchange_key_id,
        name=payload.name,
        status="idle",
        is_enabled=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[BotOut])
def list_bots(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Bot).filter(Bot.user_id == current_user.id).all()


@router.patch("/{bot_id}/toggle", response_model=BotOut)
def toggle_bot(
    bot_id: str,
    payload: BotToggle,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bot = db.query(Bot).filter(
        Bot.id == bot_id,
        Bot.user_id == current_user.id,
    ).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    bot.is_enabled = payload.is_enabled
    bot.status = "queued" if payload.is_enabled else "stopped"
    db.commit()
    db.refresh(bot)
    return bot
