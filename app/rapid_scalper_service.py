from __future__ import annotations

from datetime import datetime, timedelta, timezone


PAPER_DURATION_SECONDS = 45
FEE_BPS_PER_SIDE = 26.0
SPREAD_BPS = 8.0
SLIPPAGE_BPS_PER_SIDE = 5.0
TOTAL_COST_RATE = (
    (2 * FEE_BPS_PER_SIDE) + SPREAD_BPS + (2 * SLIPPAGE_BPS_PER_SIDE)
) / 10_000

MODE_STOP_PERCENT = {
    "conservative": 0.35,
    "momentum": 0.50,
    "bounce": 0.40,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def price_levels(entry_price: float, side: str, target_percent: float, mode: str):
    stop_percent = MODE_STOP_PERCENT[mode]
    if side == "buy":
        target_price = entry_price * (1 + target_percent / 100)
        stop_price = entry_price * (1 - stop_percent / 100)
    else:
        target_price = entry_price * (1 - target_percent / 100)
        stop_price = entry_price * (1 + stop_percent / 100)
    return target_price, stop_price, stop_percent


def paper_pnl(entry_price: float, current_price: float, side: str, amount_usd: float):
    if entry_price <= 0 or amount_usd <= 0:
        raise ValueError("Entry price and paper amount must be positive")
    direction = 1 if side == "buy" else -1
    gross_percent = direction * ((current_price - entry_price) / entry_price) * 100
    gross_usd = amount_usd * gross_percent / 100
    estimated_cost_usd = amount_usd * TOTAL_COST_RATE
    net_usd = gross_usd - estimated_cost_usd
    net_percent = (net_usd / amount_usd) * 100
    return {
        "gross_pnl_usd": gross_usd,
        "gross_pnl_percent": gross_percent,
        "estimated_cost_usd": estimated_cost_usd,
        "net_pnl_usd": net_usd,
        "net_pnl_percent": net_percent,
    }


def open_paper_trade(trade, entry_price: float, now: datetime | None = None):
    now = now or utc_now()
    target_price, stop_price, stop_percent = price_levels(
        entry_price, trade.side, trade.scalp_target_percent, trade.mode
    )
    trade.status = "paper_running"
    trade.entry_price = entry_price
    trade.current_price = entry_price
    trade.target_price = target_price
    trade.stop_price = stop_price
    trade.stop_percent = stop_percent
    trade.expires_at = now + timedelta(seconds=PAPER_DURATION_SECONDS)
    trade.last_price_at = now
    trade.data_quality = "live"
    apply_paper_price(trade, entry_price, now)
    return trade


def apply_paper_price(trade, current_price: float, now: datetime | None = None):
    now = now or utc_now()
    metrics = paper_pnl(
        float(trade.entry_price), current_price, trade.side, float(trade.amount_usd)
    )
    trade.current_price = current_price
    trade.last_price_at = now
    trade.gross_pnl_usd = metrics["gross_pnl_usd"]
    trade.gross_pnl_percent = metrics["gross_pnl_percent"]
    trade.estimated_cost_usd = metrics["estimated_cost_usd"]
    trade.pnl_usd = metrics["net_pnl_usd"]
    trade.pnl_percent = metrics["net_pnl_percent"]
    return metrics


def update_and_maybe_close(trade, current_price: float, now: datetime | None = None):
    now = now or utc_now()
    apply_paper_price(trade, current_price, now)

    target_touched = (
        current_price >= trade.target_price
        if trade.side == "buy"
        else current_price <= trade.target_price
    )
    stop_touched = (
        current_price <= trade.stop_price
        if trade.side == "buy"
        else current_price >= trade.stop_price
    )

    exit_reason = None
    if target_touched:
        exit_reason = "TARGET_REACHED"
    elif stop_touched:
        exit_reason = "PROTECTIVE_STOP"
    elif now >= trade.expires_at:
        exit_reason = "MAX_DURATION"

    if exit_reason:
        trade.status = "paper_closed"
        trade.exit_price = current_price
        trade.exit_reason = exit_reason
        trade.closed_at = now
    return trade


def remaining_seconds(trade, now: datetime | None = None) -> int:
    if trade.status != "paper_running" or not trade.expires_at:
        return 0
    now = now or utc_now()
    return max(0, int((trade.expires_at - now).total_seconds() + 0.999))
