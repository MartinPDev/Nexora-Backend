from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.strategy import Strategy
from app.schemas.strategy import StrategyCreate, StrategyOut

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.post("", response_model=StrategyOut)
def create_strategy(
    payload: StrategyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = Strategy(
        user_id=current_user.id,
        name=payload.name,
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        risk_percent=payload.risk_percent,
        take_profit_percent=payload.take_profit_percent,
        stop_loss_percent=payload.stop_loss_percent,
        is_ai_enabled=payload.is_ai_enabled,
        config_json=payload.config_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[StrategyOut])
def list_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Strategy).filter(Strategy.user_id == current_user.id).all()
