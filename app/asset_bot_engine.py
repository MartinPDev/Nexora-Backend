import json
import os
from datetime import datetime, UTC

import ccxt


BASE_DIR = "/home/marty/backend"

BOTS_FILE = os.path.join(BASE_DIR, "bots.json")
POSITIONS_FILE = os.path.join(BASE_DIR, "asset_bot_positions.json")
TRADES_FILE = os.path.join(BASE_DIR, "asset_bot_trades.json")
LOGS_FILE = os.path.join(BASE_DIR, "asset_bot_logs.json")


def load_json(path, default):
    if not os.path.exists(path):
        return default

    with open(path, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def log_event(message, level="INFO"):
    logs = load_json(LOGS_FILE, [])

    logs.append({
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "message": message
    })

    save_json(LOGS_FILE, logs[-500:])


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
    bots = load_json(BOTS_FILE, {})

    user_bots = bots.get(username, [])

    for bot in user_bots:
        if bot.get("id") != bot_id:
            continue

        bot["current_open_positions"] = current_open_positions
        bot["last_action"] = last_action
        bot["last_scan"] = datetime.now(UTC).isoformat()
        save_json(BOTS_FILE, bots)
        return True

    return False


def fetch_price(symbol):
    exchange = ccxt.kraken({
        "enableRateLimit": True
    })

    ticker = exchange.fetch_ticker(symbol)
    price = ticker.get("last")

    if price is None:
        raise ValueError(f"No live price returned for {symbol}")

    return float(price)

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
    positions = load_positions()
    positions[get_position_key(username, bot_id)] = position
    save_positions(positions)



def remove_position(username, bot_id):
    positions = load_positions()
    key = get_position_key(username, bot_id)

    if key in positions:
        del positions[key]
        save_positions(positions)
        return True

    return False


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

    save_position(username, bot_id, position)
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

    trades = load_json(TRADES_FILE, [])
    trades.append(trade)
    save_json(TRADES_FILE, trades[-1000:])

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

    if updated_position["unrealized_pnl_percent"] >= take_profit_percent:
        trade = close_paper_position(
            updated_position,
             price,
             f"TAKE_PROFIT_{take_profit_percent:.2f}_PERCENT"
        )

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "username": username,
            "bot_id": bot_id,
            "bot_name": bot.get("name", "Asset Bot"),
            "symbol": symbol,
            "price": price,
            "status": "closed_take_profit",
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

    for bot in enabled_bots:
        try:
            result = scan_asset_bot(bot)
            if result:
                results.append(result)
        except Exception as error:
            log_event(
                f"Asset bot scan failed for {bot.get('symbol', 'UNKNOWN')}: {error}",
                "ERROR"
            )

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "count": len(results),
        "results": results
    }


if __name__ == "__main__":
    print(json.dumps(scan_all_enabled_bots(), indent=2))
