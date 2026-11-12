"""Explicit-approval paper preview. Public Kraken candles; never place exchange orders."""
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.paper_wallet import PaperWallet
from app.models.desktop_paper_bot import DesktopPaperBot
from app.models.paper_preview import PaperPreviewEnrollment, PaperPreviewProposal, PaperPreviewPosition
from app.api.routes.desktop import _fetch_kraken_candles, _KRAKEN_PAIRS, _KRAKEN_INTERVALS

router = APIRouter(tags=["paper-preview"])
D = Decimal
FEE_RATE = D("0.0026")
MONEY = D("0.00000001")


def bot_owned(db, user, bot_id):
    bot = db.query(DesktopPaperBot).filter(
        DesktopPaperBot.id == bot_id, DesktopPaperBot.user_id == user.id).first()
    if bot is None:
        raise HTTPException(404, "Paper bot not found.")
    return bot


def enrollment(db, user, bot_id):
    return db.query(PaperPreviewEnrollment).filter(
        PaperPreviewEnrollment.bot_id == bot_id,
        PaperPreviewEnrollment.user_id == user.id).first()


def serial_proposal(p):
    return {
        "proposal_id": p.id, "bot_id": p.bot_id, "symbol": p.symbol,
        "side": "buy", "estimated_price": float(p.price),
        "quantity": float(p.quantity), "principal": float(p.principal),
        "estimated_fees": float(p.fee),
        "gross_committed": float(D(p.principal) + D(p.fee)),
        "payload_hash": p.payload_hash, "status": p.status,
        "expires_at": p.expires_at.isoformat() + "Z",
    }


def serial_position(p):
    return {
        "id": p.id, "bot_id": p.bot_id, "symbol": p.symbol,
        "entry_price": float(p.entry_price), "quantity": float(p.quantity),
        "amount": float(p.principal), "current_price": None,
        "unrealized_pnl": None, "take_profit_percent": 4,
        "stop_loss_percent": 2, "trailing_stop_percent": 1.5,
        "max_hold_hours": 24, "opened_at": p.opened_at.isoformat() + "Z",
    }


@router.get("/desktop/paper-preview")
def read_preview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bots = db.query(DesktopPaperBot).filter(DesktopPaperBot.user_id == user.id).all()
    enrollments = {x.bot_id: x for x in db.query(PaperPreviewEnrollment).filter(PaperPreviewEnrollment.user_id == user.id).all()}
    proposals = db.query(PaperPreviewProposal).filter(PaperPreviewProposal.user_id == user.id).all()
    positions = db.query(PaperPreviewPosition).filter(PaperPreviewPosition.user_id == user.id).all()
    opened = [p for p in positions if p.status == "OPEN"]
    now = datetime.utcnow()
    return {
        "available": True, "mode": "paper", "bots": [{
            "bot": {"id": b.id, "name": b.name, "symbol": b.symbol,
                    "timeframe": b.timeframe, "allocation": float(b.allocated_cash),
                    "allocated_cash": float(b.allocated_cash)},
            "permission": {"state": "APPROVAL_REQUIRED" if b.id in enrollments else "NOT_ENROLLED"},
            "proposals": [serial_proposal(p) for p in proposals if p.bot_id == b.id],
            "committed_gross": float(sum((D(p.principal) + D(p.entry_fee) for p in opened if p.bot_id == b.id), D(0))),
            "observer": {"available": os.getenv("NEXORA_PREVIEW_WORKER") == "YES",
                         "enabled": bool(enrollments[b.id].observer_enabled) if b.id in enrollments else False,
                         "last_result": enrollments[b.id].last_action if b.id in enrollments else "OFF",
                         "last_reason": enrollments[b.id].last_reason if b.id in enrollments else "Not enrolled."},
            "last_decision": ({"action": enrollments[b.id].last_action, "reason": enrollments[b.id].last_reason}
                              if b.id in enrollments and enrollments[b.id].last_action else None),
        } for b in bots],
        "positions": [serial_position(p) for p in opened],
        "trades": [{
            "id": p.id, "symbol": p.symbol, "entry_price": float(p.entry_price),
            "exit_price": float(p.exit_price), "pnl": float(p.pnl),
            "reason": p.exit_reason, "closed_at": p.closed_at.isoformat() + "Z",
        } for p in positions if p.status == "CLOSED"],
        "expired_proposals": sum(p.status == "PENDING" and p.expires_at <= now for p in proposals),
    }


@router.post("/desktop/paper-preview/{bot_id}/enroll")
def enroll(bot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bot_owned(db, user, bot_id)
    if not enrollment(db, user, bot_id):
        try:
            with db.begin_nested():
                db.add(PaperPreviewEnrollment(bot_id=bot_id, user_id=user.id))
                db.flush()
        except IntegrityError:
            pass
        db.commit()
    return {"bot_id": bot_id, "permission": "APPROVAL_REQUIRED", "mode": "paper"}


def ema(values, period):
    if len(values) < period:
        raise ValueError("Insufficient completed candles.")
    result = sum(values[:period]) / D(period)
    for value in values[period:]:
        result += (value - result) * D(2) / D(period + 1)
    return result


@router.post("/desktop/paper-preview/{bot_id}/scan")
async def scan(bot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import asyncio
    bot = bot_owned(db, user, bot_id)
    if not enrollment(db, user, bot_id):
        raise HTTPException(409, "Enroll this paper bot first.")
    if bot.symbol not in _KRAKEN_PAIRS or bot.timeframe not in _KRAKEN_INTERVALS:
        raise HTTPException(422, "Unsupported Kraken pair or timeframe.")
    if db.query(PaperPreviewPosition).filter(PaperPreviewPosition.bot_id == bot_id, PaperPreviewPosition.status == "OPEN").first():
        raise HTTPException(409, "Paper position already open.")
    if db.query(PaperPreviewProposal).filter(PaperPreviewProposal.bot_id == bot_id, PaperPreviewProposal.status == "PENDING", PaperPreviewProposal.expires_at > datetime.utcnow()).first():
        raise HTTPException(409, "A proposal is awaiting approval.")
    try:
        rows = await asyncio.to_thread(_fetch_kraken_candles, _KRAKEN_PAIRS[bot.symbol], _KRAKEN_INTERVALS[bot.timeframe])
    except (OSError, ValueError, TimeoutError) as exc:
        raise HTTPException(503, "Kraken candles unavailable.") from exc
    # Kraken's last row is the still-forming candle; never use it to propose a trade.
    completed = rows[:-1]
    if len(completed) < 60:
        raise HTTPException(503, "Insufficient completed Kraken candles.")
    if datetime.utcnow().timestamp() - completed[-1]["timestamp"] > 3 * _KRAKEN_INTERVALS[bot.timeframe] * 60:
        raise HTTPException(503, "Kraken candle feed is stale.")
    closes = [D(str(row["close"])) for row in completed]
    fast, slow = ema(closes, 9), ema(closes, 20)
    previous_fast, previous_slow = ema(closes[:-1], 9), ema(closes[:-1], 20)
    if not (previous_fast <= previous_slow and fast > slow):
        record = enrollment(db, user, bot_id)
        record.last_action = "REJECT"
        record.last_reason = "No completed-candle EMA9/EMA20 bullish crossover."
        record.last_scanned_at = datetime.utcnow()
        db.commit()
        return {"action": "REJECT", "reason": record.last_reason, "proposal": None}
    price = closes[-1]
    principal = min(D(str(bot.allocated_cash)) / (D(1) + FEE_RATE), D("100"))
    principal = principal.quantize(MONEY, rounding=ROUND_DOWN)
    fee = (principal * FEE_RATE).quantize(MONEY, rounding=ROUND_DOWN)
    quantity = (principal / price).quantize(D("0.000000000001"), rounding=ROUND_DOWN)
    if principal <= 0 or quantity <= 0:
        raise HTTPException(422, "Insufficient allocation for simulated entry.")
    candle = completed[-1]["timestamp"]
    immutable = {"bot_id": bot.id, "candle": candle, "price": str(price),
                 "quantity": str(quantity), "principal": str(principal), "fee": str(fee)}
    digest = hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    proposal = PaperPreviewProposal(id=str(uuid.uuid4()), user_id=user.id, bot_id=bot.id,
        symbol=bot.symbol, candle_timestamp=candle, price=price, quantity=quantity,
        principal=principal, fee=fee, payload_hash=digest,
        expires_at=datetime.utcnow() + timedelta(minutes=5))
    try:
        db.add(proposal)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This completed candle has already been evaluated.") from exc
    record = enrollment(db, user, bot_id)
    record.last_action = "PROPOSE"
    record.last_reason = "Completed-candle EMA9/EMA20 bullish crossover."
    record.last_scanned_at = datetime.utcnow()
    db.commit()
    return {"action": "PROPOSE", "proposal": serial_proposal(proposal)}


class Approval(BaseModel):
    payload_hash: str


@router.post("/desktop/paper-preview/proposals/{proposal_id}/approve")
def approve(proposal_id: str, payload: Approval, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Lock the wallet first to serialize all approvals across the account.
    wallet = db.query(PaperWallet).filter(PaperWallet.user_id == user.id).with_for_update().first()
    if wallet is None:
        raise HTTPException(409, "Paper wallet not initialized.")
    proposal = db.query(PaperPreviewProposal).filter(
        PaperPreviewProposal.id == proposal_id, PaperPreviewProposal.user_id == user.id).with_for_update().first()
    if proposal is None:
        raise HTTPException(404, "Proposal not found.")
    if proposal.status != "PENDING" or proposal.expires_at <= datetime.utcnow():
        raise HTTPException(409, "Proposal is no longer pending.")
    if payload.payload_hash != proposal.payload_hash:
        raise HTTPException(409, "Proposal payload hash mismatch.")
    bot = bot_owned(db, user, proposal.bot_id)
    if not enrollment(db, user, bot.id):
        raise HTTPException(409, "Paper bot is not enrolled.")
    if db.query(PaperPreviewPosition).filter(PaperPreviewPosition.bot_id == bot.id, PaperPreviewPosition.status == "OPEN").first():
        raise HTTPException(409, "Paper position already open.")
    cost = D(proposal.principal) + D(proposal.fee)
    if cost > D(bot.allocated_cash) or cost > D(wallet.cash_balance):
        raise HTTPException(409, "Insufficient paper cash.")
    wallet.cash_balance = D(wallet.cash_balance) - cost
    db.add(PaperPreviewPosition(id=str(uuid.uuid4()), user_id=user.id, bot_id=bot.id,
        proposal_id=proposal.id, symbol=proposal.symbol, entry_price=proposal.price,
        quantity=proposal.quantity, principal=proposal.principal, entry_fee=proposal.fee,
        peak_price=proposal.price))
    proposal.status = "APPROVED"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Approval already settled.") from exc
    return {"proposal_id": proposal.id, "status": "APPROVED", "mode": "paper"}


@router.delete("/desktop/paper-preview/proposals/{proposal_id}")
def reject(proposal_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.query(PaperPreviewProposal).filter(PaperPreviewProposal.id == proposal_id, PaperPreviewProposal.user_id == user.id).with_for_update().first()
    if p is None:
        raise HTTPException(404, "Proposal not found.")
    if p.status != "PENDING":
        raise HTTPException(409, "Proposal already finalized.")
    p.status = "REJECTED"
    db.commit()
    return {"proposal_id": p.id, "status": "REJECTED"}


@router.post("/desktop/paper-preview/{bot_id}/settle")
async def settle(bot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Check a completed public candle and settle a protective exit exactly once.

    A user-initiated settlement is required until a durable scheduled worker exists.
    """
    import asyncio
    bot = bot_owned(db, user, bot_id)
    wallet = db.query(PaperWallet).filter(PaperWallet.user_id == user.id).with_for_update().first()
    if wallet is None:
        raise HTTPException(409, "Paper wallet not initialized.")
    position = db.query(PaperPreviewPosition).filter(
        PaperPreviewPosition.bot_id == bot.id, PaperPreviewPosition.user_id == user.id,
        PaperPreviewPosition.status == "OPEN").with_for_update().first()
    if position is None:
        raise HTTPException(409, "No open paper position.")
    if bot.symbol not in _KRAKEN_PAIRS or bot.timeframe not in _KRAKEN_INTERVALS:
        raise HTTPException(422, "Unsupported Kraken pair or timeframe.")
    try:
        rows = await asyncio.to_thread(_fetch_kraken_candles, _KRAKEN_PAIRS[bot.symbol], _KRAKEN_INTERVALS[bot.timeframe])
    except (OSError, ValueError, TimeoutError) as exc:
        raise HTTPException(503, "Kraken candles unavailable.") from exc
    # Only closed candles after entry; conservatively take stop before profit if both
    # are touched within one candle. No fabricated fill at a favorable price.
    after = [row for row in rows[:-1] if datetime.utcfromtimestamp(row["timestamp"]) > position.opened_at]
    peak = D(position.peak_price)
    entry = D(position.entry_price)
    reason = None
    exit_price = None
    for candle in after:
        low, high = D(str(candle["low"])), D(str(candle["high"]))
        stop = max(entry * D("0.98"), peak * D("0.985"))
        target = entry * D("1.04")
        if low <= stop:
            reason, exit_price = "STOP_OR_TRAIL", min(stop, D(str(candle["open"])))
            break
        if high >= target:
            reason, exit_price = "TAKE_PROFIT", target
            break
        peak = max(peak, high)
    if reason is None and datetime.utcnow() - position.opened_at >= timedelta(hours=24):
        if not after:
            raise HTTPException(503, "No completed candle available to settle maximum hold.")
        reason, exit_price = "MAX_HOLD", D(str(after[-1]["close"]))
    if reason is None:
        position.peak_price = peak
        db.commit()
        return {"status": "OPEN", "bot_id": bot.id, "mode": "paper"}
    proceeds = (D(position.quantity) * exit_price).quantize(MONEY, rounding=ROUND_DOWN)
    exit_fee = (proceeds * FEE_RATE).quantize(MONEY, rounding=ROUND_DOWN)
    pnl = proceeds - exit_fee - D(position.principal) - D(position.entry_fee)
    wallet.cash_balance = D(wallet.cash_balance) + proceeds - exit_fee
    position.status = "CLOSED"
    position.closed_at = datetime.utcnow()
    position.exit_price = exit_price
    position.exit_fee = exit_fee
    position.pnl = pnl
    position.exit_reason = reason
    db.commit()
    return {"status": "CLOSED", "bot_id": bot.id, "reason": reason,
            "exit_price": float(exit_price), "pnl": float(pnl), "mode": "paper"}


@router.post("/desktop/paper-preview/{bot_id}/observer")
def observer_on(bot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bot_owned(db, user, bot_id)
    if os.getenv("NEXORA_PREVIEW_WORKER") != "YES":
        raise HTTPException(503, "Local paper observer worker is not enabled.")
    record = enrollment(db, user, bot_id)
    if record is None:
        raise HTTPException(409, "Enroll this paper bot first.")
    record.observer_enabled = True
    db.commit()
    return {"enabled": True, "mode": "paper", "approval_required": True}


@router.delete("/desktop/paper-preview/{bot_id}/observer")
def observer_off(bot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bot_owned(db, user, bot_id)
    record = enrollment(db, user, bot_id)
    if record is not None:
        record.observer_enabled = False
        db.commit()
    return {"enabled": False, "mode": "paper"}
