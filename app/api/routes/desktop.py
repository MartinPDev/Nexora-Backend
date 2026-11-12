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
            "mode": (item.config_json or {}).get("mode", "balanced"),
            "min_score": (item.config_json or {}).get("min_score"),
            "min_ai_probability": (item.config_json or {}).get("min_ai_probability"),
            "trailing_stop_percent": (item.config_json or {}).get("trailing_stop_percent"),
            "cooldown_hours": (item.config_json or {}).get("cooldown_hours"),
            "partial_take_profit_percent": float(item.take_profit_percent) if item.take_profit_percent is not None else None,
        }
        for item in strategies
    ]}


@router.get("/desktop/dashboard")
def desktop_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Account-scoped bot overview; financial metrics require a real paper ledger."""
    bots = db.query(DesktopPaperBot).filter(DesktopPaperBot.user_id == current_user.id).all()
    wallet = db.query(PaperWallet).filter(
        PaperWallet.user_id == current_user.id
    ).first()
    return {
        "bots_total": len(bots),
        "bots_running": 0,  # Desktop paper bots are configurations, not running workers.
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
    allocated = db.query(DesktopPaperBot).filter(
        DesktopPaperBot.user_id == current_user.id
    ).all()
    from app.models.paper_preview import PaperPreviewPosition
    opened = db.query(PaperPreviewPosition).filter(
        PaperPreviewPosition.user_id == current_user.id,
        PaperPreviewPosition.status == "OPEN",
    ).all()
    committed = {}
    for position in opened:
        committed[position.bot_id] = committed.get(position.bot_id, Decimal("0")) + Decimal(str(position.principal)) + Decimal(str(position.entry_fee))
    reserved = sum((max(Decimal("0"), Decimal(str(bot.allocated_cash)) - committed.get(bot.id, Decimal("0"))) for bot in allocated), Decimal("0"))
    available = Decimal(str(wallet.cash_balance)) - reserved
    return {
        "total_value": None,
        "cash": float(available),
        "paper_cash_balance": float(wallet.cash_balance),
        "reserved_cash": float(reserved),
        "allocated_cash": float(reserved),
        "available_to_allocate": float(available),
        "starting_balance": float(wallet.initial_balance),
        "position_value": None,
        "currency": wallet.currency,
        "unrealized_pnl": None,
        "return_percent": None,
        "positions": [{
            "id": p.id, "symbol": p.symbol, "amount": float(p.quantity),
            "entry_price": float(p.entry_price), "current_price": None,
            "current_value": None, "unrealized_pnl": None,
        } for p in opened],
        "history": [],
        "financial_data_status": "cash_and_reservations_only",
    }


@router.get("/desktop/wallet")
def desktop_wallet(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paper-only wallet values backed by the persisted wallet and bot allocations.

    Equity and P&L are intentionally null until a position/ledger source exists.
    """
    portfolio = desktop_portfolio(db=db, current_user=current_user)
    wallet = db.query(PaperWallet).filter(
        PaperWallet.user_id == current_user.id
    ).first()
    if wallet is None:
        raise HTTPException(status_code=503, detail="Paper wallet unavailable.")
    return {
        "starting_balance": float(wallet.initial_balance),
        "cash": float(wallet.cash_balance),
        "allocated_cash": portfolio["reserved_cash"],
        "available_to_allocate": portfolio["cash"],
        "equity": None,
        "pnl": None,
        "pnl_percent": None,
        "open_positions": len(portfolio["positions"]),
        "currency": wallet.currency,
        "mode": "paper",
        "financial_data_status": "cash_and_reservations_only",
    }


# Public Kraken OHLC data only: no API keys, orders, or trading workers.
_KRAKEN_PAIRS = {
    "BTC/USD": "XBTUSD", "ETH/USD": "ETHUSD", "XRP/USD": "XRPUSD",
    "SOL/USD": "SOLUSD", "ADA/USD": "ADAUSD", "DOGE/USD": "DOGEUSD",
    "HBAR/USD": "HBARUSD", "XLM/USD": "XLMUSD", "ICP/USD": "ICPUSD",
}
_KRAKEN_INTERVALS = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "1d": 1440,
}


def _fetch_kraken_candles(pair: str, interval: int):
    """Fetch a strictly allowlisted public Kraken OHLC feed."""
    import json
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    url = "https://api.kraken.com/0/public/OHLC?" + urlencode({
        "pair": pair, "interval": interval,
    })
    request = Request(url, headers={"User-Agent": "NexoraDesktopBeta/0.3.3"})
    with urlopen(request, timeout=10) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Kraken rejected the candle request.")
    results = payload.get("result")
    if not isinstance(results, dict):
        raise ValueError("Kraken returned an invalid OHLC response.")
    rows = next((value for key, value in results.items()
                 if key != "last" and isinstance(value, list)), None)
    if rows is None:
        raise ValueError("Kraken returned no OHLC series.")
    candles = []
    previous = -1
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError("Kraken returned an invalid OHLC row.")
        timestamp = int(row[0])
        o, h, l, c = [float(value) for value in row[1:5]]
        volume = float(row[6])
        from math import isfinite
        if (not all(isfinite(value) for value in (o, h, l, c, volume))
                or min(o, h, l, c) <= 0 or volume < 0
                or l > min(o, c) or h < max(o, c)
                or timestamp <= previous):
            raise ValueError("Kraken OHLC data failed validation.")
        candles.append({
            "timestamp": timestamp, "open": o, "high": h,
            "low": l, "close": c, "volume": volume,
        })
        previous = timestamp
    return candles


@router.get("/desktop/market-candles")
async def desktop_market_candles(
    symbol: str,
    timeframe: str,
    current_user: User = Depends(get_current_user),
):
    """Authenticated, validated Kraken public candles for the original charts."""
    import asyncio
    if symbol not in _KRAKEN_PAIRS or timeframe not in _KRAKEN_INTERVALS:
        raise HTTPException(status_code=422, detail="Unsupported Kraken market or timeframe.")
    try:
        candles = await asyncio.to_thread(
            _fetch_kraken_candles,
            _KRAKEN_PAIRS[symbol],
            _KRAKEN_INTERVALS[timeframe],
        )
    except (ValueError, OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Kraken market candles unavailable.") from exc
    return {
        "symbol": symbol, "timeframe": timeframe,
        "source": "kraken_public_ohlc",
        "timestamp_unit": "seconds",
        "candles": candles,
    }


@router.get("/desktop/positions")
def desktop_positions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Only persisted, owner-scoped simulated holdings; never invent a mark price."""
    from app.models.paper_preview import PaperPreviewPosition
    rows = db.query(PaperPreviewPosition).filter(
        PaperPreviewPosition.user_id == current_user.id,
        PaperPreviewPosition.status == "OPEN",
    ).all()
    return {
        "positions": [{
            "id": p.id, "bot_id": p.bot_id, "symbol": p.symbol,
            "quantity": float(p.quantity), "amount": float(p.quantity),
            "entry_price": float(p.entry_price), "current_price": None,
            "current_value": None, "unrealized_pnl": None,
            "source": "paper_preview",
        } for p in rows],
        "data_status": "unvalued_paper_positions",
    }


@router.get("/desktop/trades")
def desktop_trades(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Only persisted paper-executed scalper trades owned by this username."""
    rows = (
        db.query(RapidScalperTrade)
        .filter(
            RapidScalperTrade.username == current_user.username,
            RapidScalperTrade.status == "paper_executed",
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
async def desktop_markets(current_user: User = Depends(get_current_user)):
    """Public Kraken 24-hour OHLC watchlist, never simulated prices."""
    import asyncio
    from math import isfinite
    semaphore = asyncio.Semaphore(3)

    async def one(symbol, pair):
        async with semaphore:
            try:
                rows = await asyncio.to_thread(_fetch_kraken_candles, pair, 60)
                # Drop the still-forming hourly candle; require 24 completed bars.
                completed = rows[:-1][-24:]
                if len(completed) < 24:
                    return None
                opening = completed[0]["open"]
                latest = completed[-1]["close"]
                change = (latest / opening - 1) * 100
                if not isfinite(change):
                    return None
                return {
                    "symbol": symbol, "price": latest,
                    "change_percent": change,
                    "high": max(row["high"] for row in completed),
                    "low": min(row["low"] for row in completed),
                    "volume": sum(row["volume"] for row in completed),
                    "source": "kraken_public_ohlc",
                    "as_of": completed[-1]["timestamp"],
                }
            except (ValueError, OSError, TimeoutError):
                return None

    results = await asyncio.gather(*(one(symbol, pair) for symbol, pair in _KRAKEN_PAIRS.items()))
    markets = [result for result in results if result is not None]
    return {
        "markets": markets,
        "data_status": "available" if len(markets) == len(_KRAKEN_PAIRS) else "partial_or_unavailable",
        "source": "kraken_public_ohlc",
    }


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
    from app.models.paper_preview import PaperPreviewPosition
    open_positions = db.query(PaperPreviewPosition).filter(
        PaperPreviewPosition.user_id == current_user.id,
        PaperPreviewPosition.status == "OPEN",
    ).all()
    committed = {}
    for position in open_positions:
        committed[position.bot_id] = committed.get(position.bot_id, Decimal("0")) + Decimal(str(position.principal)) + Decimal(str(position.entry_fee))
    reserved = sum((max(Decimal("0"), Decimal(str(bot.allocated_cash)) - committed.get(bot.id, Decimal("0"))) for bot in existing), Decimal("0"))
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


def _owned_desktop_bot(db: Session, user_id: str, bot_id: str) -> DesktopPaperBot:
    bot = db.query(DesktopPaperBot).filter(
        DesktopPaperBot.id == bot_id,
        DesktopPaperBot.user_id == user_id,
    ).first()
    if bot is None:
        raise HTTPException(status_code=404, detail="Paper bot not found.")
    return bot


@router.post("/desktop/bots/{bot_id}/pause")
def pause_desktop_paper_bot(
    bot_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pause a configuration; never start or stop live exchange execution."""
    bot = _owned_desktop_bot(db, current_user.id, bot_id)
    bot.is_enabled = False
    bot.status = "paused"
    db.commit()
    return {"id": bot.id, "status": "paused", "is_enabled": False, "mode": "paper"}


@router.post("/desktop/bots/{bot_id}/resume")
def resume_desktop_paper_bot(
    bot_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore configured status only; paper execution is not yet implemented."""
    bot = _owned_desktop_bot(db, current_user.id, bot_id)
    bot.is_enabled = False
    bot.status = "configured"
    db.commit()
    return {
        "id": bot.id, "status": "configured", "is_enabled": False,
        "mode": "paper", "execution_available": False,
    }


@router.delete("/desktop/bots/{bot_id}")
def delete_desktop_paper_bot(
    bot_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove only the owner's inert desktop configuration, releasing reservation."""
    bot = _owned_desktop_bot(db, current_user.id, bot_id)
    from app.models.paper_preview import PaperPreviewEnrollment, PaperPreviewProposal, PaperPreviewPosition
    if db.query(PaperPreviewPosition).filter(PaperPreviewPosition.bot_id == bot_id).first():
        raise HTTPException(status_code=409, detail="Paper bot has position history and cannot be deleted.")
    if db.query(PaperPreviewProposal).filter(PaperPreviewProposal.bot_id == bot_id).first():
        raise HTTPException(status_code=409, detail="Paper bot has proposal history and cannot be deleted.")
    db.query(PaperPreviewEnrollment).filter(PaperPreviewEnrollment.bot_id == bot_id).delete()
    db.delete(bot)
    db.commit()
    return {"id": bot_id, "deleted": True, "mode": "paper"}
