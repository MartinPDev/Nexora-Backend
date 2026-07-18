from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.exchange_key import ExchangeKey
from app.services.exchange_factory import build_exchange

router = APIRouter(prefix="/exchange-test", tags=["exchange-test"])


@router.get("/balance/{exchange_key_id}")
def test_exchange_balance(
    exchange_key_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    exchange_key = (
        db.query(ExchangeKey)
        .filter(
            ExchangeKey.id == exchange_key_id,
            ExchangeKey.user_id == current_user.id,
        )
        .first()
    )

    if not exchange_key:
        raise HTTPException(status_code=404, detail="Exchange key not found")

    try:
        exchange = build_exchange(exchange_key)
        balance = exchange.fetch_balance()
        return {
            "exchange": exchange_key.exchange_name,
            "balances": balance,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Exchange connection failed: {str(e)}")
