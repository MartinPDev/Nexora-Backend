from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.encryption import encrypt_value
from app.models.user import User
from app.models.exchange_key import ExchangeKey
from app.schemas.exchange_key import ExchangeKeyCreate, ExchangeKeyOut

router = APIRouter(prefix="/exchanges", tags=["exchanges"])


@router.post("/keys", response_model=ExchangeKeyOut)
def create_exchange_key(
    payload: ExchangeKeyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = ExchangeKey(
        user_id=current_user.id,
        exchange_name=payload.exchange_name.lower(),
        api_key_encrypted=encrypt_value(payload.api_key),
        api_secret_encrypted=encrypt_value(payload.api_secret),
        api_passphrase_encrypted=encrypt_value(payload.api_passphrase) if payload.api_passphrase else None,
        is_testnet=payload.is_testnet,
        label=payload.label,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return row

@router.get("/keys", response_model=list[ExchangeKeyOut])
def list_exchange_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(ExchangeKey).filter(ExchangeKey.user_id == current_user.id).all()
