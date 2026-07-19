import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, UTC

import ccxt

from app.core.json_store import load_json, save_json, update_json
from app.reliability import record_kraken_failure, record_kraken_success, update_health


BASE_DIR = "/home/marty/backend"

BOTS_FILE = os.path.join(BASE_DIR, "bots.json")
POSITIONS_FILE = os.path.join(BASE_DIR, "asset_bot_positions.json")
TRADES_FILE = os.path.join(BASE_DIR, "asset_bot_trades.json")
LOGS_FILE = os.path.join(BASE_DIR, "asset_bot_logs.json")



def log_event(message, level="INFO"):
    def append_log(logs):
        logs.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "event": "asset_bot_engine",
            "message": message
        })
        return logs[-500:]

    update_json(LOGS_FILE, [], append_log)


def get_enabled_asset_bots(username=None):
    bots = load_json(BOTS_FILE, {})
    enabled_bots = []

    for bot_username, user_bots in bots.items():
        if username and bot_username != username:
            continue

        for bot in user_bots:
            if bot.get("bot_type") != "asset_specific":
                continue

            if bot.get("enabled") is False:
                continue

            enabled_bots.append({
                "username": bot_username,
                **bot
            })

    return enabled_bots

def update_bot_runtime_status(username, bot_id, current_open_positions, last_action):
    updated = False

    def mutate(bots):
        nonlocal updated
        for bot in bots.get(username, []):
            if bot.get("id") != bot_id:
                continue
            bot["current_open_positions"] = current_open_positions
            bot["last_action"] = last_action
            bot["last_scan"] = datetime.now(UTC).isoformat()
            updated = True
            break
        return bots

    update_json(BOTS_FILE, {}, mutate)
    return updated


def fetch_price(symbol, attempts=3, base_delay_seconds=0.5):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            exchange = ccxt.kraken({
                "enableRateLimit": True,
                "timeout": 10000
            })
            ticker = exchange.fetch_ticker(symbol)
            price = ticker.get("last")

            if price is None:
                raise ValueError(f"No live price returned for {symbol}")

            record_kraken_success()
            return float(price)
        except (
            ccxt.NetworkError,
            ccxt.RateLimitExceeded,
            ccxt.RequestTimeout,
            ccxt.ExchangeError,
            ValueError,
        ) as error:
            last_error = error
            record_kraken_failure(error)
            log_event(
                f"Kraken price request failed for {symbol} "
                f"(attempt {attempt}/{attempts}): {type(error).__name__}",
                "WARNING"
            )
            if attempt < attempts:
                delay = base_delay_seconds * (2 ** (attempt - 1))
                time.sleep(delay + random.uniform(0, delay * 0.2))

    raise RuntimeError(
        f"Kraken price request failed for {symbol} after {attempts} attempts"
    ) from last_error

def get_position_key(username, bot_id):
    return f"{username}:{bot_id}"


def load_positions():
    return load_json(POSITIONS_FILE, {})


def save_positions(positions):
    save_json(POSITIONS_FILE, positions)


def get_existing_position(username, bot_id):
    positions = load_positions()
    return positions.get(get_position_key(username, bot_id))


def save_position(username, bot_id, position):
    key = get_position_key(username, bot_id)

    def mutate(positions):
        positions[key] = position
        return positions

    update_json(POSITIONS_FILE, {}, mutate)



def remove_position(username, bot_id):
    key = get_position_key(username, bot_id)
    removed = False

    def mutate(positions):
        nonlocal removed
        if key in positions:
            del positions[key]
            removed = True
        return positions

    update_json(POSITIONS_FILE, {}, mutate)
    return removed


def open_paper_position(bot, price):
    username = bot["username"]
    bot_id = bot["id"]
    allocated_cash = float(bot.get("allocated_cash", 0) or 0)

    if allocated_cash <= 0:
        raise ValueError("Cannot open position without allocated cash")

    amount = allocated_cash / price

    position = {
        "username": username,
        "bot_id": bot_id,
        "bot_name": bot.get("name", "Asset Bot"),
        "symbol": bot["symbol"],
        "entry_price": price,
        "amount": amount,
        "allocated_cash": allocated_cash,
        "opened_at": datetime.now(UTC).isoformat(),
        "peak_price": price,
        "status": "open"
    }

    created = False
    position_key = get_position_key(username, bot_id)

    def create_if_missing(positions):
        nonlocal created, position
        existing = positions.get(position_key)
        if existing:
            position = existing
            return positions
        positions[position_key] = position
        created = True
        return positions

    update_json(POSITIONS_FILE, {}, create_if_missing)

    if not created:
        log_event(f"Duplicate open prevented for {username}/{bot_id}", "WARNING")
        return position

    update_bot_runtime_status(username, bot_id, 1, "Position Opened")
    log_event(f"Opened paper position for {bot['symbol']} using ${allocated_cash:.2f}")

    return position



def close_paper_position(position, exit_price, reason):
    entry_price = float(position.get("entry_price", 0) or 0)
    amount = float(position.get("amount", 0) or 0)

    if entry_price <= 0 or amount <= 0:
        raise ValueError("Invalid position cannot be closed")

    entry_value = amount * entry_price
    exit_value = amount * exit_price
    pnl = exit_value - entry_value
    pnl_percent = ((exit_price - entry_price) / entry_price) * 100

    trade = {
        "timestamp": datetime.now(UTC).isoformat(),
        "username": position["username"],
        "bot_id": position["bot_id"],
        "bot_name": position.get("bot_name", "Asset Bot"),
        "symbol": position["symbol"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "amount": amount,
        "entry_value": entry_value,
        "exit_value": exit_value,
        "pnl": pnl,
        "pnl_percent": pnl_percent,
        "reason": reason,
        "opened_at": position.get("opened_at"),
        "closed_at": datetime.now(UTC).isoformat()
    }

    def append_trade(trades):
        trades.append(trade)
        return trades[-1000:]

    update_json(TRADES_FILE, [], append_trade)

    remove_position(position["username"], position["bot_id"])

    update_bot_runtime_status(
        position["username"],
        position["bot_id"],
        0,
        f"Closed ({reason})"
    )


    log_event(
        f"Closed {position['symbol']} for {position['username']}: "
        f"PnL ${pnl:.4f} ({pnl_percent:.2f}%) reason={reason}"
    )

    return trade



def update_open_position(position, current_price):
    entry_price = float(position.get("entry_price", 0) or 0)
    amount = float(position.get("amount", 0) or 0)

    if entry_price <= 0 or amount <= 0:
        raise ValueError("Invalid position entry price or amount")

    previous_peak = float(position.get("peak_price", entry_price) or entry_price)
    peak_price = max(previous_peak, current_price)

    current_value = amount * current_price
    entry_value = amount * entry_price
    unrealized_pnl = current_value - entry_value
    unrealized_pnl_percent = ((current_price - entry_price) / entry_price) * 100

    position["current_price"] = current_price
    position["current_value"] = current_value
    position["unrealized_pnl"] = unrealized_pnl
    position["unrealized_pnl_percent"] = unrealized_pnl_percent
    position["peak_price"] = peak_price
    position["last_checked_at"] = datetime.now(UTC).isoformat()

    return position



def scan_asset_bot(bot):
    symbol = bot.get("symbol")
    username = bot.get("username")
    bot_id = bot.get("id")

    if not symbol or not username or not bot_id:
        log_event("Skipped bot with missing username, id, or symbol", "WARNING")
        return None

    price = fetch_price(symbol)
    existing_position = get_existing_position(username, bot_id)

    if not existing_position:
        position = open_paper_position(bot, price)

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "username": username,
            "bot_id": bot_id,
            "bot_name": bot.get("name", "Asset Bot"),
            "symbol": symbol,
            "price": price,
            "status": "opened_paper_position",
            "position": position
        }

    updated_position = update_open_position(existing_position, price)

    take_profit_percent = float(bot.get("take_profit_percent", 5.0) or 5.0)
    stop_loss_percent = float(bot.get("stop_loss_percent", 2.0) or 2.0)
    trailing_stop_percent = float(bot.get("trailing_stop_percent", 1.5) or 1.5)
    pnl_percent = updated_position["unrealized_pnl_percent"]
    peak_price = float(updated_position.get("peak_price", price) or price)
    entry_price = float(updated_position.get("entry_price", price) or price)
    peak_drawdown_percent = ((price - peak_price) / peak_price) * 100 if peak_price > 0 else 0

    exit_reason = None
    exit_status = None
    if pnl_percent <= -stop_loss_percent:
        exit_reason = f"STOP_LOSS_{stop_loss_percent:.2f}_PERCENT"
        exit_status = "closed_stop_loss"
    elif pnl_percent >= take_profit_percent:
        exit_reason = f"TAKE_PROFIT_{take_profit_percent:.2f}_PERCENT"
        exit_status = "closed_take_profit"
    elif peak_price > entry_price and peak_drawdown_percent <= -trailing_stop_percent:
        exit_reason = f"TRAILING_STOP_{trailing_stop_percent:.2f}_PERCENT"
        exit_status = "closed_trailing_stop"

    if exit_reason:
        trade = close_paper_position(updated_position, price, exit_reason)
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "username": username,
            "bot_id": bot_id,
            "bot_name": bot.get("name", "Asset Bot"),
            "symbol": symbol,
            "price": price,
            "status": exit_status,
            "trade": trade
        }

    save_position(username, bot_id, updated_position)
    update_bot_runtime_status(username, bot_id, 1, "Monitoring Position")


    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "username": username,
        "bot_id": bot_id,
        "bot_name": bot.get("name", "Asset Bot"),
        "symbol": symbol,
        "price": price,
        "status": "position_updated",
        "position": updated_position
    }

    log_event(
        f"Updated {symbol} for {username}: "
        f"PnL ${updated_position['unrealized_pnl']:.4f} "
        f"({updated_position['unrealized_pnl_percent']:.2f}%)"
    )

    return result


def scan_all_enabled_bots(username=None):
    enabled_bots = get_enabled_asset_bots(username=username)
    results = []

    def scan_isolated(bot):
        try:
            return scan_asset_bot(bot)
        except Exception as error:
            log_event(
                f"Asset bot scan failed for {bot.get('symbol', 'UNKNOWN')}: "
                f"{type(error).__name__}: {error}",
                "ERROR"
            )
            return None

    if enabled_bots:
        worker_count = min(10, len(enabled_bots))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="asset-bot"
        ) as executor:
            futures = [executor.submit(scan_isolated, bot) for bot in enabled_bots]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)

    positions = load_positions()
    update_health(
        active_bots=len(enabled_bots),
        open_positions=len(positions),
        last_engine_cycle=datetime.now(UTC).isoformat(),
        last_engine_error=None,
    )

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "count": len(results),
        "results": results
    }

if __name__ == "__main__":
    print(json.dumps(scan_all_enabled_bots(), indent=2))
