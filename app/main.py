# ============================================================
# NEXORA MAIN APPLICATION ENTRY POINT
# ============================================================
import json
import os
import time
import threading
import sqlite3
import hashlib
import secrets
import stripe
import ccxt
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Literal
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.json_store import load_json as load_json_file, save_json as save_json_file
from app.reliability import health_snapshot
from app.models.rapid_scalper_trade import RapidScalperTrade
from fastapi.staticfiles import StaticFiles


def save_bot_control(username: str, enabled: bool):
    data = {
        "username": username,
        "bot_enabled": enabled
    }

    with open(CONTROL_FILE, "w") as f:
        json.dump(data, f, indent=2)

    return data

DASHBOARD_FILE = "/home/marty/sniper_bot/dashboard_status.json"
CONTROL_FILE = "/home/marty/sniper_bot/bot_control.json"
TRADE_RESULTS_FILE = "/home/marty/sniper_bot/trade_results.csv"
SETTINGS_FILE = "/home/marty/sniper_bot/bot_settings.json"
BOT_LOG_FILE = "/home/marty/sniper_bot/bot.log"
EQUITY_HISTORY_FILE = "/home/marty/sniper_bot/equity_history.json"
USERS_DB = "/home/marty/backend/users.db"
BILLING_FILE = "/home/marty/backend/billing.json"
BOTS_FILE = "/home/marty/backend/bots.json"
ASSET_BOT_POSITIONS_FILE = "/home/marty/backend/asset_bot_positions.json"
STRATEGIES_FILE = "/home/marty/backend/strategies.json"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_IDS = {
    "basic": "price_1TRn6bHuABr3asZe11WVF4ka",
    "pro": "price_1TS6v6HuABr3asZe3PtQCPvb",
    "elite": "price_1TS70AHuABr3asZeoRB21fM9"
}

stripe.api_key = STRIPE_SECRET_KEY
SESSIONS = {}
# ============================================================
# IMPORTS
# ============================================================
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from app.api.routes.strategies import router as strategies_router
from app.api.routes.bots import router as bots_router
from app.core.config import get_settings
from app.api.routes.auth import router as auth_router
from app.api.routes.users import router as users_router
from app.api.routes.exchanges import router as exchanges_router
from app.api.routes.exchange_test import router as exchange_test_route


class AuthRequest(BaseModel):
    username: str
    password: str
    email: str | None = None

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="static"), name="static")
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="app/static"), name="static")

def require_elite_access(x_plan: str = Header(None)):
    if x_plan != "elite":
        raise HTTPException(
            status_code=403,
            detail="Elite membership required."
        )
    return True

class RapidScalperRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    amount_usd: float
    scalp_target_percent: Literal[0.5, 1.0]
    mode: Literal["conservative", "momentum", "bounce"] = "conservative"


class RapidScalperResponse(BaseModel):
    status: str
    message: str
    symbol: str
    side: str
    amount_usd: float
    scalp_target_percent: float
    mode: str
    created_at: str
    entry_price: float | None = None
    exit_price: float | None = None
    pnl_usd: float | None = None
    pnl_percent: float | None = None

class RapidScalperHistoryItem(BaseModel):
    id: str
    status: str
    symbol: str
    side: str
    amount_usd: float
    scalp_target_percent: float
    mode: str
    created_at: str
    entry_price: float | None = None
    exit_price: float | None = None
    pnl_usd: float | None = None
    pnl_percent: float | None = None


app.include_router(strategies_router, prefix="/api/v1")
app.include_router(bots_router, prefix="/api/v1")
app.include_router(exchanges_router, prefix="/api/v1")
app.include_router(exchange_test_route, prefix="/api/v1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_default_billing(username: str):
    return {
        "username": username,
        "plan": "free",
        "subscription_status": "inactive",
        "features": {
            "max_bots": 1,
            "max_positions": 2,
            "paper_trading": True,
            "live_trading": False,
            "advanced_ai": False
        }
    }


def init_users_db():
    conn = sqlite3.connect(USERS_DB)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            email_verified INTEGER DEFAULT 0,
            verification_token TEXT
        )
    """)

    try:
        cur.execute("ALTER TABLE app_users ADD COLUMN email TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE app_users ADD COLUMN email_verified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE app_users ADD COLUMN verification_token TEXT")
    except sqlite3.OperationalError:
        pass


    conn.commit()
    conn.close()


def hash_password(password: str, salt: str):
    value = password + salt
    return hashlib.sha256(value.encode()).hexdigest()

def get_app_user(username: str):
    conn = sqlite3.connect(USERS_DB)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT username, password_hash, salt, email_verified
        FROM app_users
        WHERE username = ?
        """,
        (username,)
    )

    user = cur.fetchone()
    conn.close()

    return user



def save_equity_snapshot(data):
    snapshots = []

    if os.path.exists(EQUITY_HISTORY_FILE):
        try:
            with open(EQUITY_HISTORY_FILE, "r") as f:
                snapshots = json.load(f)
        except Exception:
            snapshots = []

    snapshot = {
        "updated_at": data.get("updated_at"),
        "equity": data.get("equity"),
        "pnl": data.get("pnl"),
        "pnl_percent": data.get("pnl_percent")
    }

    snapshots.append(snapshot)
    snapshots = snapshots[-200:]

    with open(EQUITY_HISTORY_FILE, "w") as f:
        json.dump(snapshots, f, indent=2)

def load_strategies():
    return load_json_file(STRATEGIES_FILE, {})


def save_strategies(strategies):
    save_json_file(STRATEGIES_FILE, strategies)


def load_bots():
    return load_json_file(BOTS_FILE, {})


def save_bots(bots):
    save_json_file(BOTS_FILE, bots)


def count_user_bots(username: str):
    bots = load_bots()
    return len(bots.get(username, []))


def get_user_billing(username: str):
    if not os.path.exists(BILLING_FILE):
        return get_default_billing(username)

    with open(BILLING_FILE, "r") as f:
        data = json.load(f)

    return data.get(username, get_default_billing(username))

def activate_user_plan(username: str, plan: str):
    plans = {
        "basic": {
            "max_bots": 1,
            "max_positions": 2,
            "paper_trading": True,
            "live_trading": False,
            "advanced_ai": False
        },
        "pro": {
            "max_bots": 3,
            "max_positions": 5,
            "paper_trading": True,
            "live_trading": True,
            "advanced_ai": True
        },
        "premium": {
            "max_bots": 10,
            "max_positions": 15,
            "paper_trading": True,
            "live_trading": True,
            "advanced_ai": True
        }
    }

    if plan not in plans:
        return {"error": "Invalid plan"}

    billing = {}

    if os.path.exists(BILLING_FILE):
        with open(BILLING_FILE, "r") as f:
            billing = json.load(f)

    billing[username] = {
        "username": username,
        "plan": plan,
        "subscription_status": "active",
        "features": plans[plan]
    }

    with open(BILLING_FILE, "w") as f:
        json.dump(billing, f, indent=2)

    return billing[username]

@app.post("/elite/rapid-scalper/preview", response_model=RapidScalperResponse)
def rapid_scalper_preview(
    request: RapidScalperRequest,
    elite_access: bool = Depends(require_elite_access),
    db: Session = Depends(get_db)
):
    allowed_symbols = ["BTC/USD", "ETH/USD", "XRP/USD", "SOL/USD", "ADA/USD", "DOGE/USD"]

    if request.symbol not in allowed_symbols:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported symbol. Allowed symbols: {allowed_symbols}"
        )

    if request.amount_usd < 5:
        raise HTTPException(
            status_code=400,
            detail="Minimum Rapid Scalper amount is $5."
        )

    trade = RapidScalperTrade(
        symbol=request.symbol,
        side=request.side,
        amount_usd=request.amount_usd,
        scalp_target_percent=request.scalp_target_percent,
        mode=request.mode
    )

    db.add(trade)
    db.commit()
    db.refresh(trade)

    return RapidScalperResponse(
        status=trade.status,
        message="Rapid Scalper setup created and saved.",
        symbol=trade.symbol,
        side=trade.side,
        amount_usd=trade.amount_usd,
        scalp_target_percent=trade.scalp_target_percent,
        mode=trade.mode,
        created_at=trade.created_at.isoformat(),
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        pnl_usd=trade.pnl_usd,
        pnl_percent=trade.pnl_percent
    )

MARKET_PRICE_CACHE = {}
MARKET_PRICE_CACHE_TTL_SECONDS = 3
MARKET_PRICE_SYMBOLS = {
    "BTC-USD": "BTC/USD",
    "ETH-USD": "ETH/USD",
    "XRP-USD": "XRP/USD",
    "SOL-USD": "SOL/USD",
    "ADA-USD": "ADA/USD",
    "DOGE-USD": "DOGE/USD",
    "HBAR-USD": "HBAR/USD",
    "XLM-USD": "XLM/USD",
    "ICP-USD": "ICP/USD",
    "WLD-USD": "WLD/USD",
    "ONDO-USD": "ONDO/USD"
}

def update_market_price_cache_loop():
    exchange = ccxt.kraken({
        "enableRateLimit": True,
        "timeout": 10000
    })
    kraken_symbols = list(MARKET_PRICE_SYMBOLS.values())

    while True:
        cycle_started = time.monotonic()
        try:
            tickers = exchange.fetch_tickers(kraken_symbols)
            refreshed_at = datetime.utcnow().isoformat()
            cached_at = time.time()

            for cache_symbol, kraken_symbol in MARKET_PRICE_SYMBOLS.items():
                ticker = tickers.get(kraken_symbol)
                if not ticker or ticker.get("last") is None:
                    continue

                MARKET_PRICE_CACHE[cache_symbol] = {
                    "cached_at": cached_at,
                    "data": {
                        "symbol": kraken_symbol,
                        "price": ticker.get("last"),
                        "change_usd": ticker.get("change"),
                        "change_percent": ticker.get("percentage"),
                        "timestamp": refreshed_at,
                        "source": "background_cache"
                    }
                }
        except Exception as e:
            print(f"Market price cache bulk update failed: {e}")

        elapsed = time.monotonic() - cycle_started
        time.sleep(max(0, 1.0 - elapsed))

@app.get("/market/live-price/{symbol}")
def get_live_market_price(symbol: str):
    allowed_symbols = {
        "BTC-USD": "BTC/USD",
        "ETH-USD": "ETH/USD",
        "XRP-USD": "XRP/USD",
        "SOL-USD": "SOL/USD",
        "ADA-USD": "ADA/USD",
        "DOGE-USD": "DOGE/USD",
        "HBAR-USD": "HBAR/USD",
        "XLM-USD": "XLM/USD",
        "ICP-USD": "ICP/USD",
        "WLD-USD": "WLD/USD",
        "ONDO-USD": "ONDO/USD"
    }

    if symbol not in allowed_symbols:
        raise HTTPException(
            status_code=400,
            detail="Unsupported symbol."
        )

    now_ts = time.time()
    cached = MARKET_PRICE_CACHE.get(symbol)

    if cached and now_ts - cached["cached_at"] < MARKET_PRICE_CACHE_TTL_SECONDS:
        return cached["data"]

    exchange = ccxt.kraken({
        "enableRateLimit": True
    })

    ticker = exchange.fetch_ticker(allowed_symbols[symbol])

    data = {
        "symbol": allowed_symbols[symbol],
        "price": ticker.get("last"),
        "change_usd": ticker.get("change"),
        "change_percent": ticker.get("percentage"),
        "timestamp": datetime.utcnow().isoformat()
    }

    MARKET_PRICE_CACHE[symbol] = {
        "cached_at": now_ts,
        "data": data
    }

    return data


@app.post("/elite/rapid-scalper/run-paper", response_model=RapidScalperResponse)
def rapid_scalper_run_paper(
    request: RapidScalperRequest,
    elite_access: bool = Depends(require_elite_access),
    db: Session = Depends(get_db)
):
    allowed_symbols = ["BTC/USD", "ETH/USD", "XRP/USD", "SOL/USD", "ADA/USD", "DOGE/USD"]

    if request.symbol not in allowed_symbols:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported symbol. Allowed symbols: {allowed_symbols}"
        )

    if request.amount_usd < 5:
        raise HTTPException(
            status_code=400,
            detail="Minimum Rapid Scalper amount is $5."
        )

    exchange = ccxt.kraken({
        "enableRateLimit": True
    })

    ticker = exchange.fetch_ticker(request.symbol)
    entry_price = float(ticker["last"])

    if request.side == "buy":
        exit_price = entry_price * (1 + (request.scalp_target_percent / 100))
        pnl_percent = request.scalp_target_percent
    else:
        exit_price = entry_price * (1 - (request.scalp_target_percent / 100))
        pnl_percent = request.scalp_target_percent

    pnl_usd = request.amount_usd * (pnl_percent / 100)

    trade = RapidScalperTrade(
        symbol=request.symbol,
        side=request.side,
        amount_usd=request.amount_usd,
        scalp_target_percent=request.scalp_target_percent,
        mode=request.mode,
        status="paper_executed",
        entry_price=entry_price,
        exit_price=exit_price,
        pnl_usd=pnl_usd,
        pnl_percent=pnl_percent,
        closed_at=datetime.utcnow()
    )

    db.add(trade)
    db.commit()
    db.refresh(trade)

    return RapidScalperResponse(
        status=trade.status,
        message="Rapid Scalper paper trade executed and saved.",
        symbol=trade.symbol,
        side=trade.side,
        amount_usd=trade.amount_usd,
        scalp_target_percent=trade.scalp_target_percent,
        mode=trade.mode,
        created_at=trade.created_at.isoformat(),
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        pnl_usd=trade.pnl_usd,
        pnl_percent=trade.pnl_percent
    )


@app.get("/elite/rapid-scalper/history", response_model=list[RapidScalperHistoryItem])
def rapid_scalper_history(
    elite_access: bool = Depends(require_elite_access),
    db: Session = Depends(get_db)
):
    trades = (
        db.query(RapidScalperTrade)
        .order_by(RapidScalperTrade.created_at.desc())
        .limit(50)
        .all()
    )

    return [
        RapidScalperHistoryItem(
            id=trade.id,
            status=trade.status,
            symbol=trade.symbol,
            side=trade.side,
            amount_usd=trade.amount_usd,
            scalp_target_percent=trade.scalp_target_percent,
            mode=trade.mode,
            created_at=trade.created_at.isoformat(),
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            pnl_usd=trade.pnl_usd,
            pnl_percent=trade.pnl_percent
        )
        for trade in trades
    ]


@app.on_event("startup")
def startup():
    init_users_db()
    from app.asset_bot_supervisor import start_asset_bot_supervisor

    start_asset_bot_supervisor()

    market_price_thread = threading.Thread(
        target=update_market_price_cache_loop,
        daemon=True
    )
    market_price_thread.start()

@app.get("/health")
def health_check():
    return health_snapshot()

@app.get("/dashboard/{username}")
def get_dashboard(username: str):
    if not os.path.exists(DASHBOARD_FILE):
        return {
            "error": "Dashboard file not found",
            "path": DASHBOARD_FILE
        }

    with open(DASHBOARD_FILE, "r") as f:
        data = json.load(f)

    if data.get("username") != username:
        return {
            "error": "No dashboard data found for this user"
        }

    save_equity_snapshot(data)
    return data

@app.get("/bots/{username}")
def get_bots(username: str):
    bots = load_bots()
    return bots.get(username, [])

@app.get("/asset-bot-positions/{username}")
def get_asset_bot_positions(username: str):
    if not os.path.exists(ASSET_BOT_POSITIONS_FILE):
        return []

    with open(ASSET_BOT_POSITIONS_FILE, "r") as f:
        positions = json.load(f)

    user_positions = []

    exchange = ccxt.kraken({
        "enableRateLimit": True
    })

    for position_key, position in positions.items():
        if position.get("username") != username:
            continue

        live_position = dict(position)

        try:
            symbol = live_position.get("symbol")
            entry_price = float(live_position.get("entry_price") or 0)
            amount = float(live_position.get("amount") or 0)

            ticker = exchange.fetch_ticker(symbol)
            current_price = float(ticker.get("last") or ticker.get("close") or entry_price)

            current_value = amount * current_price
            cost_basis = amount * entry_price
            unrealized_pnl = current_value - cost_basis
            unrealized_pnl_percent = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0

            live_position["current_price"] = current_price
            live_position["current_value"] = current_value
            live_position["unrealized_pnl"] = unrealized_pnl
            live_position["unrealized_pnl_percent"] = unrealized_pnl_percent
            live_position["last_checked_at"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            live_position["pnl_error"] = str(e)

        user_positions.append({
            "position_key": position_key,
            **live_position
        })

    return user_positions


@app.post("/asset-bot-close-position/{username}/{bot_id}")
def close_asset_bot_position(username: str, bot_id: str):
    from app.asset_bot_engine import (
        fetch_price,
        get_existing_position,
        close_paper_position
    )

    position = get_existing_position(username, bot_id)

    if not position:
        return {
            "error": "No open position found for this bot"
        }

    price = fetch_price(position["symbol"])

    trade = close_paper_position(
        position,
        price,
        "MANUAL_CLOSE"
    )

    bots = load_bots()
    user_bots = bots.get(username, [])

    for bot in user_bots:
        if bot.get("id") == bot_id:
            bot["enabled"] = False
            bot["status"] = "paused"
            bot["current_open_positions"] = 0
            bot["last_action"] = "Closed manually - paused"
            bot["last_scan"] = datetime.now().isoformat()
            save_bots(bots)
            break

    return {
        "success": True,
        "status": "closed_manual",
        "trade": trade
    }

@app.get("/bot-control/{username}")
def get_bot_control(username: str):
    try:
        if not os.path.exists(CONTROL_FILE):
            return {
                "username": username,
                "bot_enabled": False
            }

        with open(CONTROL_FILE, "r") as f:
            data = json.load(f)

        return {
            "username": data.get("username", username),
            "bot_enabled": bool(data.get("bot_enabled", False))
        }

    except Exception as e:
        return {
            "username": username,
            "bot_enabled": False,
            "error": str(e)
        }

@app.get("/settings/{username}")
def get_settings(username: str):
    default_settings = {
        "username": username,
        "risk_percent": 1.0,
        "max_positions": 5,
        "stop_loss_percent": 2.0,
        "partial_take_profit_percent": 2.0,
        "trailing_stop_percent": 1.5,
        "bot_mode": "paper"
    }

    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(default_settings, f, indent=2)
        return default_settings

    with open(SETTINGS_FILE, "r") as f:
        data = json.load(f)

    if data.get("username") != username:
        return default_settings

    return data

@app.get("/strategies/{username}")
def get_strategies(username: str):
    strategies = load_strategies()
    user_strategies = strategies.get(username, [])
    bots = load_bots().get(username, [])

    usage = {}
    for bot in bots:
        strategy_id = bot.get("strategy_id")
        if strategy_id:
            usage[strategy_id] = usage.get(strategy_id, 0) + 1

    return [
        {**strategy, "assigned_bot_count": usage.get(strategy.get("id"), 0)}
        for strategy in user_strategies
    ]


def _strategy_number(payload, field, default, minimum, maximum):
    try:
        value = float(payload.get(field, default))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{field} must be a number")

    if value < minimum or value > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be between {minimum} and {maximum}",
        )
    return value


@app.post("/strategies/{username}/create")
def create_strategy(username: str, strategy: dict):
    strategies = load_strategies()
    user_strategies = strategies.setdefault(username, [])

    name = str(strategy.get("name", "")).strip()
    if len(name) < 2 or len(name) > 60:
        raise HTTPException(
            status_code=422,
            detail="Strategy name must be between 2 and 60 characters",
        )

    mode = str(strategy.get("mode", "balanced")).lower()
    if mode not in {"conservative", "balanced", "aggressive"}:
        raise HTTPException(status_code=422, detail="Invalid strategy mode")

    if any(item.get("name", "").lower() == name.lower() for item in user_strategies):
        raise HTTPException(status_code=409, detail="A strategy with this name already exists")

    new_strategy = {
        "id": secrets.token_hex(8),
        "name": name,
        "min_score": _strategy_number(strategy, "min_score", 60, 0, 100),
        "min_ai_probability": _strategy_number(strategy, "min_ai_probability", 0.50, 0, 1),
        "stop_loss_percent": _strategy_number(strategy, "stop_loss_percent", 2.0, 0.1, 25),
        "partial_take_profit_percent": _strategy_number(strategy, "partial_take_profit_percent", 4.0, 0.1, 100),
        "trailing_stop_percent": _strategy_number(strategy, "trailing_stop_percent", 1.5, 0.1, 25),
        "cooldown_hours": _strategy_number(strategy, "cooldown_hours", 2, 0, 168),
        "mode": mode,
        "created_at": datetime.now().isoformat(),
    }

    user_strategies.append(new_strategy)
    save_strategies(strategies)
    return {**new_strategy, "assigned_bot_count": 0}


@app.delete("/strategies/{username}/{strategy_id}")
def delete_strategy(username: str, strategy_id: str):
    bots = load_bots().get(username, [])
    assigned = [bot for bot in bots if bot.get("strategy_id") == strategy_id]
    if assigned:
        raise HTTPException(
            status_code=409,
            detail=f"Strategy is assigned to {len(assigned)} bot(s). Reassign or delete those bots first.",
        )

    strategies = load_strategies()
    user_strategies = strategies.get(username, [])
    remaining = [item for item in user_strategies if item.get("id") != strategy_id]
    if len(remaining) == len(user_strategies):
        raise HTTPException(status_code=404, detail="Strategy not found")

    strategies[username] = remaining
    save_strategies(strategies)
    return {"success": True, "deleted_strategy_id": strategy_id}

@app.post("/settings/{username}")
def save_settings(username: str, settings: dict):
    settings["username"] = username

    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

    return settings

@app.post("/auth/register")
def register_user(auth: AuthRequest):
    username = auth.username.strip().lower()
    password = auth.password.strip()

    if not username or not password:
        return {"error": "Username and password are required"}

    salt = secrets.token_hex(16)
    password_hash = hash_password(password, salt)

    try:
        conn = sqlite3.connect(USERS_DB)
        cur = conn.cursor()

        verification_token = secrets.token_hex(32)

        cur.execute(
            """
            INSERT INTO app_users
            (username, email, password_hash, salt, email_verified, verification_token)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, auth.email, password_hash, salt, 0, verification_token)
        )

        conn.commit()
        conn.close()

        return {
            "success": True,
            "username": username,
            "message": "Account created. Verify email before login.",
            "verification_link": f"http://127.0.0.1:8000/auth/verify-email/{verification_token}"
        }

    except sqlite3.IntegrityError:
        return {"error": "Username already exists"}

@app.post("/auth/register-basic")
def register_basic_user(auth: AuthRequest):
    username = auth.username.strip().lower()
    password = auth.password.strip()

    if not username or not password:
        return {"error": "Username and password are required"}

    existing_user = get_app_user(username)

    if not existing_user:
        salt = secrets.token_hex(16)
        password_hash = hash_password(password, salt)

        try:
            conn = sqlite3.connect(USERS_DB)
            cur = conn.cursor()

            cur.execute(
                "INSERT INTO app_users (username, password_hash, salt) VALUES (?, ?, ?)",
                (username, password_hash, salt)
            )

            conn.commit()
            conn.close()

        except sqlite3.IntegrityError:
            return {"error": "Username already exists"}

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": STRIPE_PRICE_IDS["basic"],
                    "quantity": 1
                }
            ],
            success_url="http://127.0.0.1:8000/login",
            cancel_url="http://127.0.0.1:8000/signup-basic",
            metadata={
                "username": username,
                "plan": "basic"
            }
        )

        return {
            "success": True,
            "username": username,
            "checkout_url": session.url
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/", response_class=HTMLResponse)
def landing_page():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>AI Crypto Trading Bot</title>
</head>
<body>

    <div class="hero">
        <h1>AI Crypto Trading, Simplified.</h1>

        <p>
            A smart trading bot platform built to monitor markets,
            manage positions, track performance, and help users trade
            with more structure instead of emotion.
        </p>

        <a class="cta" href="/signup-basic">Start Basic Plan</a>
        <a class="cta secondary" href="/login">Login</a>
    </div>

    <div class="section">
        <h2>What You Get</h2>

        <div class="grid">
            <div class="card">
                <h3>AI Trade Signals</h3>
                <p class="muted">
                    Uses strategy scoring and AI probability to filter
                    weak setups before trades are considered.
                </p>
            </div>

            <div class="card">
                <h3>Risk Protection</h3>
                <p class="muted">
                    Stop losses, cooldowns, partial profit taking,
                    and trailing stops help protect capital.
                </p>
            </div>

            <div class="card">
                <h3>Live Dashboard</h3>
                <p class="muted">
                    Track equity, cash, open trades, performance,
                    logs, and strategy activity from one place.
                </p>
            </div>

            <div class="card">
                <h3 class="card-title-with-info">
                    Bot Control
                    <button onclick="openBotInfo()" style="background:#38bdf8 !important;color:#fff !important;border-radius:50% !important;">i</button>

                </h3>

                <p class="muted">
                    Start, stop, monitor, and manage bots directly
                    through the platform.
                </p>
            </div>
        </div>
    </div>

    <div class="section">
        <h2>Start Simple</h2>

        <div class="grid">
            <div class="card">
                <h3>Basic</h3>
                <div class="price">$9.99/mo</div>

                <p class="muted">Includes:</p>
                <p>1 Bot</p>
                <p>2 Open Positions</p>
                <p>Paper Trading Access</p>
                <p>Dashboard Access</p>

                <a class="cta" href="/signup-basic">Start Basic</a>
            </div>

            <div class="card">
                <h3>Pro</h3>
                <div class="price">$49.99/mo</div>

                <p class="muted">Coming soon:</p>
                <p>Live Trading</p>
                <p>Advanced AI</p>
                <p>More Bots</p>
                <p>More Positions</p>
            </div>

            <div class="card">
                <h3>Elite</h3>
                <div class="price">$99.99/mo</div>

                <p class="muted">Coming soon:</p>
                <p>Multi Bot Power</p>
                <p>VIP Tools</p>
                <p>Priority Features</p>
                <p>Maximum Scaling</p>
            </div>
        </div>
    </div>

    <div class="section">
        <div class="card">
            <h2>Built For Discipline</h2>
            <p class="muted">
                This platform is designed to reduce emotional trading,
                protect downside risk, and give users a clear view of
                what their bot is doing.
            </p>
            <p class="muted">
                Trading involves risk. This software does not guarantee profits.
            </p>
        </div>
    </div>

    <div class="footer">
        AI Trading Bot Platform • Built for smarter crypto automation
    </div>
    <!-- BOT INFO MODAL -->
    <div id="botInfoModal" class="info-modal">
        <div class="info-box">
            <button class="close-info" onclick="closeBotInfo()">×</button>

            <h2>How the Bot Works</h2>

            <p>
                The trading bot is an automated assistant that monitors live market data, analyzes trading signals,
                and manages simulated or connected exchange trades based on the strategy settings you choose.
            </p>

            <h3>What the bot does</h3>
            <p>
                When the bot is running, it scans selected trading pairs, reads market candles, checks indicators,
                evaluates AI confidence, and decides whether the current conditions are strong enough to open,
                hold, or close a position.
            </p>

            <h3>How decisions are made</h3>
            <p>
                The bot uses a combination of technical indicators, price movement, risk settings, stop loss,
                take profit, and AI probability scoring.
            </p>
        </div>
    </div>

</body>
</html>
"""


@app.post("/auth/login")
def login_user(auth: AuthRequest):
    username = auth.username.strip().lower()
    password = auth.password.strip()

    user = get_app_user(username)

    if not user:
        return {"error": "Invalid username or password"}

    stored_username, stored_hash, salt, email_verified = user

    if email_verified != 1:
        return {"error": "Email not verified"}

    password_hash = hash_password(password, salt)

    if password_hash != stored_hash:
        return {"error": "Invalid username or password"}

    token = secrets.token_hex(32)
    SESSIONS[token] = username

    return {
        "success": True,
        "username": username,
        "token": token
    }

@app.get("/auth/verify-email/{token}")
def verify_email(token: str):
    conn = sqlite3.connect(USERS_DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT username FROM app_users WHERE verification_token = ?",
        (token,)
    )

    user = cur.fetchone()

    if not user:
        conn.close()
        return {"error": "Invalid or expired verification token"}

    cur.execute(
        """
        UPDATE app_users
        SET email_verified = 1, verification_token = NULL
        WHERE verification_token = ?
        """,
        (token,)
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Email verified. You can now login."
    }


@app.get("/signup-basic", response_class=HTMLResponse)
def signup_basic_page():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Basic Plan Signup</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #0f172a;
            color: white;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }

        .box {
            background: #1e293b;
            padding: 30px;
            border-radius: 14px;
            width: 390px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.35);
        }

        input {
            width: 100%;
            padding: 12px;
            margin-top: 10px;
            margin-bottom: 15px;
            border-radius: 8px;
            border: none;
        }

        button {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            background: #f59e0b;
            color: white;
            font-weight: bold;
            cursor: pointer;
        }

        .small {
            color: #94a3b8;
            font-size: 14px;
            margin-bottom: 20px;
        }

        #message {
            margin-top: 15px;
            color: #f87171;
        }
    </style>
</head>
<body>
    <div class="box">
        <h2>Start Basic Plan</h2>

        <div class="small">
            $9.99/month • 1 bot • 2 open positions • paper trading
        </div>

        <input id="username" placeholder="Username">
        <input id="password" type="password" placeholder="Password">

        <button onclick="signupBasic()">Continue to Checkout</button>

        <div id="message"></div>
    </div>

<script>
async function signupBasic() {
    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;
    const message = document.getElementById("message");

    const res = await fetch("/auth/register-basic", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            username: username,
            password: password
        })
    });

    const data = await res.json();

    if (data.error) {
        message.innerText = data.error;
        return;
    }

    if (data.checkout_url) {
        window.location.href = data.checkout_url;
    }
}
</script>
</body>
</html>
"""


@app.get("/billing/{username}")
def get_billing(username: str):
    if not os.path.exists(BILLING_FILE):
        return get_default_billing(username)

    with open(BILLING_FILE, "r") as f:
        data = json.load(f)

    return data.get(username, get_default_billing(username))

@app.post("/billing/{username}/set-plan/{plan}")
def set_plan(username: str, plan: str):
    plans = {
        "free": {
            "max_bots": 1,
            "max_positions": 2,
            "paper_trading": True,
            "live_trading": False,
            "advanced_ai": False
        },
        "basic": {
            "max_bots": 1,
            "max_positions": 2,
            "paper_trading": True,
            "live_trading": False,
            "advanced_ai": False
        },

        "pro": {
            "max_bots": 3,
            "max_positions": 5,
            "paper_trading": True,
            "live_trading": True,
            "advanced_ai": True
        },
        "premium": {
            "max_bots": 10,
            "max_positions": 15,
            "paper_trading": True,
            "live_trading": True,
            "advanced_ai": True
        }
    }
    if plan not in plans:
        return {"error": "Invalid plan"}
    billing = {}

    if os.path.exists(BILLING_FILE):
        with open(BILLING_FILE, "r") as f:
            billing = json.load(f)

    billing[username] = {
        "username": username,
        "plan": plan,
        "subscription_status": "active" if plan != "free" else "inactive",
        "features": plans[plan]
    }
    with open(BILLING_FILE, "w") as f:
        json.dump(billing, f, indent=2)

    return billing[username]

@app.post("/billing/{username}/checkout/{plan}")
def create_checkout_session(username: str, plan: str):
    if plan not in STRIPE_PRICE_IDS:
        return {"error": "Invalid plan"}

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": STRIPE_PRICE_IDS[plan],
                    "quantity": 1
                }
            ],
            success_url="http://127.0.0.1:8000/dashboard-ui/" + username,
            cancel_url="http://127.0.0.1:8000/dashboard-ui/" + username,
            metadata={
                "username": username,
                "plan": plan
            }
        )

        return {
            "checkout_url": session.url
        }

    except Exception as e:
        return {
            "error": str(e)
        }

@app.post("/billing/{username}/checkout/basic")
def create_basic_checkout(username: str):
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": STRIPE_PRICE_IDS["basic"],
                    "quantity": 1
                }
            ],
            success_url="http://127.0.0.1:8000/dashboard-ui/" + username,
            cancel_url="http://127.0.0.1:8000/dashboard-ui/" + username,
            metadata={
                "username": username,
                "plan": "basic"
            }
        )

        return {"checkout_url": session.url}

    except Exception as e:
        return {"error": str(e)}

@app.post("/billing/{username}/checkout/pro")
def checkout_pro(username: str):
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{
            "price": STRIPE_PRICE_IDS["pro"],
            "quantity": 1
        }],
        success_url=f"http://127.0.0.1:8000/dashboard-ui/{username}",
        cancel_url=f"http://127.0.0.1:8000/dashboard-ui/{username}",
        metadata={
            "username": username,
            "plan": "pro"
        }
    )

    return {"checkout_url": session.url}

@app.post("/billing/{username}/checkout/premium")
def checkout_premium(username: str):
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{
            "price": STRIPE_PRICE_IDS["premium"],
            "quantity": 1
        }],
        success_url=f"http://127.0.0.1:8000/dashboard-ui/{username}",
        cancel_url=f"http://127.0.0.1:8000/dashboard-ui/{username}",
        metadata={
            "username": username,
            "plan": "elite"
        }
    )

    return {"checkout_url": session.url}


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        return {"error": str(e)}

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        usename = None
        plan = None

        if session.metadata:
            username = session.metadata["username"] if "username" in session.metadata else None
            plan = session.metadata["plan"] if "plan" in session.metadata else None

        if username and plan:
            activate_user_plan(username, plan)

    return {"success": True}


@app.post("/bots/{username}/create")
def create_bot(username: str, bot: dict):
    billing = get_user_billing(username)
    features = billing["features"]

    current_bot_count = count_user_bots(username)

    if current_bot_count >= features["max_bots"]:
        return {
            "error": "Bot limit reached",
            "plan": billing["plan"],
            "max_bots": features["max_bots"],
            "upgrade_required": True
        }

    try:
        allocated_cash = float(bot.get("allocated_cash", 0))
    except (TypeError, ValueError):
        return {
            "error": "Allocated cash must be a valid number"
        }

    if allocated_cash <= 0:
        return {
            "error": "Allocated cash must be greater than $0"
        }

    strategy_id = str(bot.get("strategy_id", "")).strip()
    user_strategies = load_strategies().get(username, [])
    selected_strategy = next(
        (item for item in user_strategies if item.get("id") == strategy_id),
        None,
    )
    if not selected_strategy:
        return {"error": "Choose a valid strategy before creating this bot"}

    bots = load_bots()

    if username not in bots:
        bots[username] = []

    existing_allocated_cash = 0.0

    for existing_bot in bots.get(username, []):
        try:
            existing_allocated_cash += float(existing_bot.get("allocated_cash", 0) or 0)
        except (TypeError, ValueError):
            continue

    available_cash = None

    if os.path.exists(DASHBOARD_FILE):
        try:
            with open(DASHBOARD_FILE, "r") as f:
                dashboard_data = json.load(f)

            if dashboard_data.get("username") == username:
                available_cash = float(dashboard_data.get("cash", 0))
        except Exception:
            available_cash = None

    if available_cash is not None:
        remaining_allocatable_cash = available_cash - existing_allocated_cash

        if allocated_cash > remaining_allocatable_cash:
            return {
                "error": (
                    f"Allocated cash cannot exceed remaining allocatable cash "
                    f"(${remaining_allocatable_cash:.2f}). "
                    f"Available cash: ${available_cash:.2f}. "
                    f"Already allocated: ${existing_allocated_cash:.2f}."
                )
            }

    new_bot = {
        "id": secrets.token_hex(8),
        "name": bot.get("name", "New Bot"),
        "symbol": bot.get("symbol", "BTC/USD"),
        "timeframe": bot.get("timeframe", "15m"),
        "risk_percent": bot.get("risk_percent", 1.0),
        "strategy_id": selected_strategy["id"],
        "strategy_name": selected_strategy["name"],
        "strategy_mode": selected_strategy["mode"],
        "min_score": selected_strategy["min_score"],
        "min_ai_probability": selected_strategy["min_ai_probability"],
        "stop_loss_percent": selected_strategy["stop_loss_percent"],
        "take_profit_percent": selected_strategy["partial_take_profit_percent"],
        "trailing_stop_percent": selected_strategy["trailing_stop_percent"],
        "cooldown_hours": selected_strategy["cooldown_hours"],
        "allocated_cash": allocated_cash,
        "bot_type": "asset_specific",
        "mode": "paper",
        "max_open_positions": features["max_positions"],
        "current_open_positions": 0,
        "last_scan": "Not scanned yet",
        "last_action": "Created",
        "status": "active",
        "enabled": True,
        "created_at": datetime.now().isoformat()
    }

    bots[username].append(new_bot)
    save_bots(bots)
    return new_bot



@app.post("/bots/{username}/{bot_id}/pause")
def pause_bot(username: str, bot_id: str):
    bots = load_bots()
    user_bots = bots.get(username, [])

    for bot in user_bots:
        if bot.get("id") == bot_id:
            bot["enabled"] = False
            bot["status"] = "paused"
            bot["last_action"] = "Paused by user"
            save_bots(bots)
            return bot

    return {
        "error": "Bot not found",
        "bot_id": bot_id
    }


@app.post("/bots/{username}/{bot_id}/resume")
def resume_bot(username: str, bot_id: str):
    bots = load_bots()
    user_bots = bots.get(username, [])

    for bot in user_bots:
        if bot.get("id") == bot_id:
            bot["enabled"] = True
            bot["status"] = "active"
            bot["last_action"] = "Resumed by user"
            save_bots(bots)
            return bot

    return {
        "error": "Bot not found",
        "bot_id": bot_id
    }




@app.delete("/bots/{username}/{bot_id}")
def delete_bot(username: str, bot_id: str):
    bots = load_bots()

    user_bots = bots.get(username, [])
    if os.path.exists(ASSET_BOT_POSITIONS_FILE):
        with open(ASSET_BOT_POSITIONS_FILE, "r") as f:
            positions = json.load(f)

        position_key = f"{username}:{bot_id}"

        if position_key in positions:
            return {
                "error": "Cannot delete bot while position is open. Close the position first."
            }

    updated_bots = [
        bot for bot in user_bots
        if bot.get("id") != bot_id
    ]

    bots[username] = updated_bots
    save_bots(bots)

    return {
        "success": True,
        "deleted_bot_id": bot_id
    }


@app.get("/trade-history/{username}")
def get_trade_history(username: str):
    if not os.path.exists(TRADE_RESULTS_FILE):
        return []

    trades = []

    with open(TRADE_RESULTS_FILE, "r") as f:
        lines = f.readlines()

    if len(lines) <= 1:
        return []

    headers = lines[0].strip().split(",")

    for line in lines[1:]:
        values = line.strip().split(",")

        if len(values) != len(headers):
            continue

        trade = dict(zip(headers, values))

        if trade.get("username") == username:
            trades.append(trade)

    return trades[-20:]

@app.get("/bot-logs/{username}")
def get_bot_logs(username: str):
    if not os.path.exists(BOT_LOG_FILE):
        return []

    with open(BOT_LOG_FILE, "r") as f:
        lines = f.readlines()

    clean_lines = []

    for line in lines[-80:]:
        line = line.strip()

        if not line:
            continue

        if username in line or "[PAPER]" in line or "Trading mode" in line:
            clean_lines.append(line)

    return clean_lines[-50:]


@app.post("/bot-control/{username}/start")
def start_bot(username: str):
    return save_bot_control(username, True)


@app.post("/bot-control/{username}/stop")
def stop_bot(username: str):
    return save_bot_control(username, False)

@app.get("/equity-history/{username}")
def get_equity_history(username: str):
    if not os.path.exists(EQUITY_HISTORY_FILE):
        return []

    with open(EQUITY_HISTORY_FILE, "r") as f:
        data = json.load(f)

    return data[-200:]

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>AI Bot Login</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #0f172a;
            color: white;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }

        .box {
            background: #1e293b;
            padding: 30px;
            border-radius: 14px;
            width: 360px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.35);
        }

        input {
            width: 100%;
            padding: 12px;
            margin-top: 10px;
            margin-bottom: 15px;
            border-radius: 8px;
            border: none;
        }

        button {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            background: #22c55e;
            color: white;
            font-weight: bold;
            cursor: pointer;
        }

        .link {
            color: #38bdf8;
            cursor: pointer;
            margin-top: 15px;
            display: block;
            text-align: center;
        }

        #message {
            margin-top: 15px;
            color: #f87171;
        }
    </style>
</head>
<body>
    <div class="box">
        <h2 id="title">Login</h2>

        <input id="username" placeholder="Username">
        <input id="password" type="password" placeholder="Password">

        <button onclick="submitAuth()">Login</button>

        <span class="link" onclick="toggleMode()">
            Need an account? Register
        </span>

        <div id="message"></div>
    </div>

<script>
let mode = "login";

function toggleMode() {
    const title = document.getElementById("title");
    const button = document.querySelector("button");
    const link = document.querySelector(".link");

    if (mode === "login") {
        mode = "register";
        title.innerText = "Register";
        button.innerText = "Create Account";
        link.innerText = "Already have an account? Login";
    } else {
        mode = "login";
        title.innerText = "Login";
        button.innerText = "Login";
        link.innerText = "Need an account? Register";
    }
}

async function submitAuth() {
    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;
    const message = document.getElementById("message");

    const res = await fetch("/auth/" + mode, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            username: username,
            password: password
        })
    });

    const data = await res.json();

    if (data.error) {
        message.innerText = data.error;
        return;
    }

    if (mode === "register") {
        message.style.color = "#22c55e";
        message.innerText = "Account created. You can now login.";
        toggleMode();
        return;
    }

    localStorage.setItem("bot_token", data.token);
    localStorage.setItem("bot_username", data.username);

    window.location.href = "/dashboard-ui/" + data.username;
}
</script>
</body>
</html>
"""
# ============================================================
# MARKET DATA ENDPOINTS
# ============================================================

KRAKEN_PAIR_MAP = {
    "BTC/USD": "XXBTZUSD",
    "ETH/USD": "XETHZUSD",
    "XRP/USD": "XXRPZUSD",
    "SOL/USD": "SOLUSD",
    "ADA/USD": "ADAUSD",
    "DOGE/USD": "XDGUSD",
    "HBAR/USD": "HBARUSD",
    "XLM/USD": "XXLMZUSD",
    "ICP/USD": "ICPUSD",
}


@app.get("/api/market/candles")
def get_market_candles(symbol: str = "BTC/USD", interval: int = 5):
    pair = KRAKEN_PAIR_MAP.get(symbol)

    if not pair:
        raise HTTPException(status_code=400, detail="Unsupported symbol")

    if interval not in [1, 5, 15, 30, 60, 240, 1440]:
        interval = 5

    url = (
        "https://api.kraken.com/0/public/OHLC?"
        + urllib.parse.urlencode({
            "pair": pair,
            "interval": interval
        })
    )

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        if data.get("error"):
            raise HTTPException(status_code=502, detail=data["error"])

        result = data.get("result", {})
        ohlc_key = next((key for key in result.keys() if key != "last"), None)

        if not ohlc_key:
            return {"symbol": symbol, "candles": []}

        candles = []

        for row in result[ohlc_key][-200:]:
            candles.append({
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
            })

        return {
            "symbol": symbol,
            "interval": interval,
            "candles": candles
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/dashboard-ui/{username}", response_class=HTMLResponse)
def dashboard_ui(username: str):
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>AI Trading Bot Dashboard</title>
    <link rel="stylesheet" href="/static/style.css">

    <style>

        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: Arial, sans-serif;
            background:
                radial-gradient(circle at top left, rgba(56,189,248,0.16), transparent 28%),
                radial-gradient(circle at top right, rgba(34,197,94,0.12), transparent 24%),
                #020617;
            color: white;
            margin: 0;
            padding: 24px;
        }}

        .premium-topbar,
        .card,
        .profit-ticker,
        .terminal-pill {{
            background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 16px;
            box-shadow: 0 12px 30px rgba(0,0,0,0.35);
        }}

        .premium-topbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 25px;
            margin-bottom: 25px;
        }}

        h1 {{
            font-size: 34px;
            margin: 0;
        }}

        h2 {{
            font-size: 20px;
            margin-top: 0;
            color: #e2e8f0;
        }}

        .sub,
        .label {{
            color: #94a3b8;
        }}

        .label {{
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 12px;
        }}

        .value {{
            font-size: 30px;
            font-weight: bold;
            margin-top: 8px;
            color: #e2e8f0;
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 20px;
            margin-bottom: 25px;
        }}

        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1.6fr;
            gap: 25px;
        }}

        .history-console-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            align-items: start;
            margin-top: 25px;
            margin-bottom: 25px;
        }}

        .compact-dropdown-card {{
            margin-top: 0 !important;
        }}

        @media (max-width: 900px) {{
            .grid,
            .grid-2 {{
                grid-template-columns: 1fr;
            }}

            .history-console-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        .card {{
            padding: 22px;
            margin-bottom: 25px;
            overflow: hidden;
            position: relative;
            z-index: 0;
        }}

        .card:hover {{
            border-color: rgba(56,189,248,0.45);
        }}

        input,
        select {{
            background: #020617;
            color: white;
            border: 1px solid #334155 !important;
            outline: none;
        }}

        button {{
            transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
        }}

        button:hover {{
            transform: translateY(-2px);
            opacity: 0.95;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            background: #020617;
            border: 1px solid #1e293b;
            border-radius: 14px;
            overflow: hidden;
        }}

        th,
        td {{
            padding: 14px;
            text-align: left;
            border-bottom: 1px solid #334155;
            color: #e2e8f0;
        }}

        th {{
            color: #94a3b8;
            font-size: 14px;
        }}

        .terminal-bg {{
            background-size: 28px 28px;
        }}

        .terminal-strip {{
            display: flex;
            gap: 14px;
            flex-wrap: wrap;
            margin-bottom: 25px;
        }}

        .terminal-pill {{
            display: inline-block;
            color: #cbd5e1;
            padding: 10px 14px;
            border-radius: 999px;
            font-size: 13px;
            margin: 4px;
        }}

        .terminal-pill strong {{
            color: #38bdf8;
        }}

        .premium-badge {{
            padding: 8px 12px;
            border-radius: 999px;
            background: rgba(56,189,248,0.15);
            color: #7dd3fc;
            border: 1px solid rgba(56,189,248,0.35);
            font-size: 13px;
            font-weight: bold;
        }}

        .live-dot {{
            display: inline-block;
            width: 9px;
            height: 9px;
            background: #22c55e;
            border-radius: 50%;
            margin-right: 8px;
            box-shadow: 0 0 14px rgba(34,197,94,0.9);
        }}

        .profit-ticker {{
            width: 100%;
            overflow: hidden;
            white-space: nowrap;
            margin: 10px 0 20px 0;
            height: 28px;
            line-height: 28px;
            font-size: 12px;
            padding: 0 12px;
        }}

        .profit-ticker-track {{
            display: flex;
            gap: 60px;
            width: max-content;
            animation: profitTickerScroll 45s linear infinite;
        }}

        @keyframes profitTickerScroll {{
            0% {{
                transform: translateX(0);
            }}
            100% {{
                transform: translateX(-50%);
            }}
        }}

        .profit-ticker-content {{
            color: #cbd5e1;
            font-size: 12px;
            white-space: nowrap;
        }}

        .ticker-profit {{
            color: #22c55e !important;
        }}

        .ticker-loss {{
            color: #ef4444 !important;
        }}

        .console-card {{
            padding: 0;
            overflow: hidden;
            margin-bottom: 25px;
        }}

        .console-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 18px 22px;
            cursor: pointer;
            border-bottom: 1px solid rgba(56,189,248,0.16);
            background: linear-gradient(90deg, rgba(15,23,42,0.95), rgba(2,6,23,0.95));
        }}

        .console-header h2 {{
            margin: 0;
        }}

        .console-subtitle {{
            margin-top: 6px;
            font-size: 12px;
            color: #94a3b8;
        }}

        .console-panel {{
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
        }}

        .console-panel.open {{
            max-height: 320px;
        }}

        .log-console {{
            margin: 0;
            background: #020617;
            border-top: 1px solid rgba(56,189,248,0.12);
            padding: 14px;
            height: 260px;
            overflow-y: auto;
            font-family: Consolas, monospace;
            font-size: 12px;
            color: #94a3b8;
            white-space: pre-wrap;
        }}

        .log-console-live {{
            color: #22c55e;
        }}


    </style>
</head>
<body class="terminal-bg">
    <script>
        window.DASHBOARD_USERNAME = "{username}";
    </script>

    <div class="premium-topbar">
        <div>

            <div class="terminal-pill">Mode: <strong>ELITE</strong></div>
            <div class="terminal-pill">Exchange: <strong>KRAKEN READY</strong></div>
            <div class="terminal-pill">Risk Engine: <strong>ACTIVE</strong></div>
            <div class="terminal-pill">Market Feed: <strong>LIVE</strong></div>
        </div>


        <div>
            <h1>Nexora AI Trading Dashboard</h1>
            <div class="sub">Elite automation, market intelligence, and performance tracking.</div>
        </div>

        <div class="premium-badge">
            ELITE MODE
        </div>
    </div>

    <div class="terminal-strip">
        <div class="terminal-pill">
            <span id="bot_dot" class="live-dot"></span>
            Auto Opportunity Bot: <strong id="bot_status_text">CHECKING...</strong>
            <div style="margin-top:8px;font-size:13px;line-height:1.5;color:#94a3b8;">
                 Scans supported markets for stronger opportunities using AI confidence, strategy scoring, and risk controls.
            </div>
        </div>
    </div>

       <div class="profit-ticker">
           <div class="profit-ticker-track">
               <div id="profit_ticker_content" class="profit-ticker-content">
                   Loading live account feed...
               </div>

               <div id="profit_ticker_content_clone" class="profit-ticker-content">
                   Loading live account feed...
               </div>
           </div>
       </div>

<div style="margin-bottom: 25px;">
    <button
        onclick="startBot()"
        style="padding:12px 18px; border:none; border-radius:10px; background:#22c55e; color:white; font-weight:bold; cursor:pointer;">
        Start Auto Bot
    </button>

    <button
        onclick="stopBot()"
         style="padding:12px 18px; border:none; border-radius:10px; background:#ef4444; color:white; font-weight:bold; cursor:pointer; margin-left:10px;">
         Stop Auto Bot
    </button>

    <button onclick="openDashboardBotInfo()" style="background:#38bdf8;color:white;">i</button>

</div>

    <button
    onclick="logout()"
    style="
    padding:12px 18px;
    border:none;
    border-radius:10px;
    background:#64748b;
    color:white;
    font-weight:bold;
    cursor:pointer;
    margin-left:10px;
    ">
    Logout
    </button>

    <span
    id="bot_status"
    style="
    margin-left:15px;
    color:#94a3b8;
    "
    >
    Checking bot status...
    </span>

    <div class="card" style="margin-bottom:22px;">
        <div class="label">Total Portfolio Value</div>
        <div class="value" id="equity" style="font-size:34px;">$0.00</div>

        <div id="pnl" class="value" style="font-size:16px;margin-top:6px;">$0.00</div>

        <div class="grid" style="margin-top:22px;">
            <div>
                <div class="label">Cash Balance</div>
                <div class="value" id="cash">$0.00</div>
            </div>

            <div>
                <div class="label">Open Position Value</div>
                <div class="value" id="position_value">$0.00</div>
            </div>

            <div>
                <div class="label">Open Positions</div>
                <div class="value" id="open_positions">0</div>
            </div>
        </div>
    </div>

<div class="grid-2">
    <div class="card" id="strategy_builder_card" style="grid-column:1 / -1;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;">
            <div>
                <div style="color:#38bdf8;font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;">Bot playbook</div>
                <h2 style="margin:5px 0 6px;">Strategy Builder</h2>
                <p style="color:#94a3b8;margin:0;max-width:720px;line-height:1.55;">
                    Choose how selective and protective your bots should be. Save the strategy, then assign it when you create an Asset-Specific Bot.
                </p>
            </div>
            <button onclick="openStrategyInfo()" type="button" style="background:#0f172a;border:1px solid #334155;color:#cbd5e1;padding:9px 12px;border-radius:9px;">How it works</button>
        </div>

        <div style="margin-top:20px;">
            <div style="font-size:13px;font-weight:700;color:#cbd5e1;margin-bottom:9px;">1. Start with a preset</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;">
                <button type="button" onclick="applyStrategyPreset('conservative')" class="strategy-preset" data-mode="conservative" style="text-align:left;padding:14px;border-radius:10px;border:1px solid #334155;background:#0f172a;color:white;cursor:pointer;">
                    <strong style="display:block;color:#60a5fa;">Conservative</strong>
                    <span style="display:block;color:#94a3b8;font-size:12px;margin-top:5px;">Fewer entries, tighter risk limits.</span>
                </button>
                <button type="button" onclick="applyStrategyPreset('balanced')" class="strategy-preset" data-mode="balanced" style="text-align:left;padding:14px;border-radius:10px;border:1px solid #38bdf8;background:rgba(56,189,248,.08);color:white;cursor:pointer;">
                    <strong style="display:block;color:#38bdf8;">Balanced</strong>
                    <span style="display:block;color:#94a3b8;font-size:12px;margin-top:5px;">A practical default for most bots.</span>
                </button>
                <button type="button" onclick="applyStrategyPreset('aggressive')" class="strategy-preset" data-mode="aggressive" style="text-align:left;padding:14px;border-radius:10px;border:1px solid #334155;background:#0f172a;color:white;cursor:pointer;">
                    <strong style="display:block;color:#f59e0b;">Aggressive</strong>
                    <span style="display:block;color:#94a3b8;font-size:12px;margin-top:5px;">More entries with wider risk limits.</span>
                </button>
            </div>
        </div>

        <div style="margin-top:20px;display:grid;grid-template-columns:minmax(0,2fr) minmax(260px,1fr);gap:18px;align-items:start;">
            <div>
                <div style="font-size:13px;font-weight:700;color:#cbd5e1;margin-bottom:9px;">2. Name and tune the controls</div>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;">
                    <label style="color:#cbd5e1;font-size:13px;">Strategy name
                        <input id="strategy_name" maxlength="60" placeholder="e.g. Balanced XLM" oninput="updateStrategyPreview()" style="width:100%;margin-top:6px;padding:11px;border-radius:8px;border:1px solid #334155;background:#020617;color:white;">
                    </label>
                    <label style="color:#cbd5e1;font-size:13px;">Minimum signal score <span title="Higher values allow fewer, stronger signals." style="color:#64748b;">ⓘ</span>
                        <input id="strategy_score" type="number" min="0" max="100" step="1" value="60" oninput="updateStrategyPreview()" style="width:100%;margin-top:6px;padding:11px;border-radius:8px;border:1px solid #334155;background:#020617;color:white;">
                    </label>
                    <label style="color:#cbd5e1;font-size:13px;">Minimum AI confidence <span title="0.50 means 50% confidence." style="color:#64748b;">ⓘ</span>
                        <input id="strategy_ai" type="number" min="0" max="1" step="0.05" value="0.50" oninput="updateStrategyPreview()" style="width:100%;margin-top:6px;padding:11px;border-radius:8px;border:1px solid #334155;background:#020617;color:white;">
                    </label>
                    <label style="color:#cbd5e1;font-size:13px;">Stop loss (%)
                        <input id="strategy_stop_loss" type="number" min="0.1" max="25" step="0.1" value="2" oninput="updateStrategyPreview()" style="width:100%;margin-top:6px;padding:11px;border-radius:8px;border:1px solid #334155;background:#020617;color:white;">
                    </label>
                    <label style="color:#cbd5e1;font-size:13px;">Take profit (%)
                        <input id="strategy_take_profit" type="number" min="0.1" max="100" step="0.1" value="4" oninput="updateStrategyPreview()" style="width:100%;margin-top:6px;padding:11px;border-radius:8px;border:1px solid #334155;background:#020617;color:white;">
                    </label>
                    <label style="color:#cbd5e1;font-size:13px;">Trailing stop (%)
                        <input id="strategy_trailing" type="number" min="0.1" max="25" step="0.1" value="1.5" oninput="updateStrategyPreview()" style="width:100%;margin-top:6px;padding:11px;border-radius:8px;border:1px solid #334155;background:#020617;color:white;">
                    </label>
                    <label style="color:#cbd5e1;font-size:13px;">Cooldown (hours)
                        <input id="strategy_cooldown" type="number" min="0" max="168" step="0.5" value="2" oninput="updateStrategyPreview()" style="width:100%;margin-top:6px;padding:11px;border-radius:8px;border:1px solid #334155;background:#020617;color:white;">
                    </label>
                </div>
            </div>

            <aside style="background:#020617;border:1px solid #334155;border-radius:12px;padding:16px;">
                <div style="font-size:12px;color:#38bdf8;font-weight:800;text-transform:uppercase;letter-spacing:.1em;">Strategy summary</div>
                <h3 id="strategy_preview_name" style="margin:9px 0 8px;">Balanced strategy</h3>
                <p id="strategy_preview_text" style="color:#94a3b8;font-size:13px;line-height:1.55;margin:0 0 14px;"></p>
                <div id="strategy_validation" style="min-height:18px;color:#fca5a5;font-size:12px;margin-bottom:10px;"></div>
                <button id="strategy_save_button" onclick="createStrategy()" type="button" style="width:100%;padding:11px 14px;border:none;border-radius:9px;background:#22c55e;color:white;font-weight:800;cursor:pointer;">Save strategy</button>
                <div id="strategy_status" role="status" style="margin-top:10px;color:#94a3b8;font-size:13px;"></div>
            </aside>
        </div>

        <div style="margin-top:24px;border-top:1px solid #1e293b;padding-top:18px;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
                <div>
                    <h3 style="margin:0 0 4px;">Saved strategies</h3>
                    <div style="color:#64748b;font-size:12px;">Assigned strategies cannot be deleted until their bots are removed.</div>
                </div>
                <span id="strategy_count" style="color:#94a3b8;font-size:13px;"></span>
            </div>
            <div style="overflow-x:auto;margin-top:12px;">
                <table style="min-width:900px;">
                    <thead><tr><th>Name</th><th>Preset</th><th>Signal filter</th><th>Stop</th><th>Target</th><th>Trailing</th><th>Cooldown</th><th>Bots</th><th>Action</th></tr></thead>
                    <tbody id="strategies"></tbody>
                </table>
            </div>
        </div>
    </div>



    <div class="card">
        <h2>Asset-Specific Bots</h2>

        <p style="color:#94a3b8;margin-top:-5px;margin-bottom:15px;">
            Create bots tied to a specific trading pair. These bots are dedicated to the market you select and are separate from the Auto Opportunity Bot.
        </p>

        <div style="color:#94a3b8;margin-bottom:10px;">
            Available to allocate: <strong id="available_to_allocate">$0.00</strong>
        </div>

        <div style="margin-bottom:15px;">
            <input
                id="new_bot_name"
                placeholder="Bot name"
                style="padding:10px;border-radius:8px;border:none;margin-right:8px;"
            >

            <select
                id="new_bot_symbol"
                style="padding:10px;border-radius:8px;border:none;margin-right:8px;"
            >
                <option value="BTC/USD">BTC/USD</option>
                <option value="ETH/USD">ETH/USD</option>
                <option value="XRP/USD">XRP/USD</option>
                <option value="SOL/USD">SOL/USD</option>
                <option value="ADA/USD">ADA/USD</option>
                <option value="DOGE/USD">DOGE/USD</option>
                <option value="HBAR/USD">HBAR/USD</option>
                <option value="XLM/USD">XLM/USD</option>
                <option value="ICP/USD">ICP/USD</option>
                <option value="WLD/USD">WLD/USD</option>
                <option value="ONDO/USD">ONDO/USD</option>
            </select>

            <select id="new_bot_strategy" style="padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:white;margin-right:8px;min-width:190px;">
                <option value="">Choose a strategy</option>
            </select>

            <input
                id="new_bot_allocated_cash"
                type="number"
                min="1"
                step="0.01"
                placeholder="Allocated cash $"
                style="padding:10px;border-radius:8px;border:none;margin-right:8px;width:150px;"
            >

            <button
                onclick="createBot()"
                style="
                padding:10px 14px;
                border:none;
                border-radius:8px;
                background:#22c55e;
                color:white;
                font-weight:bold;
                cursor:pointer;
                "

            >
                Create Bot
            </button>

            <span id="bot_create_status" style="margin-left:12px;color:#94a3b8;"></span>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Pair</th>
                    <th>Strategy</th>
                    <th>Allocated Cash</th>
                    <th>Price</th>
                    <th>$ change</th>
                    <th>% Change</th>
                    <th>Status</th>
                    <th>Positions</th>
                    <th>Last Updated</th>
                    <th>Last Action</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody id="my_bots"></tbody>
        </table>
    </div>
</div>

    <div class="card">
        <h2 onclick="toggleOpenTrades()" style="cursor:pointer;">Open Trades ▼</h2>
        <div id="open_trades_panel" style="display:none;">
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Entry</th>
                    <th>Amount</th>
                    <th>Peak</th>
                    <th>Partial Taken</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="positions"></tbody>
        </table>
        </div>
    </div>


    <div class="history-console-grid">
    <div class="card compact-dropdown-card">
        <h2

            onclick="toggleTradeHistory()"
            style="cursor:pointer;"
        >
            Trade History ▼
        </h2>

        <div id="trade_history_panel" style="display:none;">

        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Amount</th>
                    <th>Score</th>
                    <th>AI Prob</th>
                    <th>PnL</th>
                    <th>Result</th>
                </tr>
            </thead>
            <tbody id="trade_history"></tbody>
        </table>
        </div>
        </div>



        <div class="card console-card compact-dropdown-card">
            <div class="console-header" onclick="toggleBotConsole()">
                <div>
                    <h2>Live Bot Console</h2>
                    <div class="console-subtitle">
                        <span class="live-dot"></span>
                        <span class="log-console-live">STREAMING</span>
                    </div>
                </div>

                <div id="bot_console_arrow" class="console-arrow">▼</div>
            </div>

            <div id="bot_console_panel" class="console-panel open">
                <pre id="bot_logs" class="log-console">Waiting for logs...</pre>
            </div>
        </div>
    </div>

    <div class="card" style="margin-top:25px;">
        <h2>Bot Settings</h2>

        <label>Risk %</label><br>
        <input id="risk_percent" type="number" step="0.1"><br><br>

        <label>Max Positions</label><br>
        <input id="max_positions" type="number"><br><br>

        <label>Stop Loss %</label><br>
        <input id="stop_loss_percent" type="number" step="0.1"><br><br>

        <label>Partial Take Profit %</label><br>
        <input id="partial_take_profit_percent" type="number" step="0.1"><br><br>

        <label>Trailing Stop %</label><br>
        <input id="trailing_stop_percent" type="number" step="0.1"><br><br>

        <label>Bot Mode</label><br>
        <select id="bot_mode">
            <option value="paper">Paper</option>
            <option value="live">Live</option>
        </select><br><br>

        <button onclick="saveSettings()">
            Save Settings
        </button>

        <span id="settings_status" style="margin-left:15px;color:#94a3b8;"></span>
    </div>

<div class="card" style="margin-top:25px;">
    <h2>Subscription</h2>

    <div class="label">Current Plan</div>
    <div class="value" id="billing_plan">Loading...</div>

    <br>

    <div class="label">Subscription Status</div>
    <div class="value" id="billing_status">Loading...</div>

    <br>

    <div class="label">Features</div>
    <div
        id="billing_features"
        style="color:#94a3b8; margin-top:10px;"
    ></div>

    <hr style="margin:25px 0; border-color:#334155;">

    <h3 style="margin-bottom:15px;">Upgrade Plans</h3>

    <div
        style="
        display:grid;
        grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
        gap:15px;
        "

    >

        <div
            style="
            background:#0f172a;
            padding:18px;
            border-radius:12px;
            border:1px solid #334155;
            "

        >
            <h3>FREE</h3>
            <p style="color:#94a3b8;">Starter Access</p>
            <p>$0/mo</p>

            <button
                onclick="changePlan('free')"
                style="
                width:100%;
                padding:10px;
                border:none;
                border-radius:8px;
                background:#475569;
                color:white;
                cursor:pointer;
                "

            >
                Select
            </button>
        </div>

            <div
            style="
            background:#0f172a;
            padding:18px;
            border-radius:12px;
            border:1px solid #f59e0b;
            "
            >
            <h3>BASIC</h3>

            <p style="color:#94a3b8;">
            1 Bot Running
            </p>

            <p style="color:#94a3b8;">
            2 Open Positions
            </p>

            <p style="color:#94a3b8;">
            Paper Trading Included
            </p>

            <p>$9.99/mo</p>

            <button
            onclick="changePlan('basic')"
            style="
            width:100%;
            padding:10px;
            border:none;
            border-radius:8px;
            background:#f59e0b;
            color:white;
            cursor:pointer;
            "
            >
            Upgrade
            </button>
            </div>


        <div
            style="
            background:#0f172a;
            padding:18px;
            border-radius:12px;
            border:1px solid #22c55e;
            "
        >

             <h3>PRO</h3>
             <p style="color:#94a3b8;">
             Live Trading Enabled
             </p>

             <p style="color:#94a3b8;">
             3 Bots • 5 Positions
             </p>

             <p style="color:#94a3b8;">
             Advanced AI Signals
             </p>

             <p>$49.99/mo</p>

             <button
                 onclick="changePlan('pro')"
                 style="
                 width:100%;
                 padding:10px;
                 border:none;
                 border-radius:8px;
                 background:#22c55e;
                 color:white;
                 cursor:pointer;
                 "

             >
             Upgrade
             </button>
         </div>

         <div
             style="
             background:#0f172a;
             padding:18px;
             border-radius:12px;
             border:1px solid #38bdf8;
             "

         >
             <h3>ELITE</h3>
             <p style="color:#94a3b8;">
             10 Bots Running
             </p>

             <p style="color:#94a3b8;">
             15 Positions Open
             </p>

             <p style="color:#94a3b8;">
             Priority Features + AI
             </p>

             <p style="color:#94a3b8;">
             Future VIP Tools Included
             </p>

             <p>$99.99/mo Elite Access</p>

             <button
                 onclick="changePlan('premium')"
                 style="
                 width:100%;
                 padding:10px;
                 border:none;
                 border-radius:8px;
                 background:#38bdf8;
                 color:white;
                 cursor:pointer;
                 "

         >
                 Upgrade
             </button>
         </div>

     </div>
 </div>

<div class="card" style="margin-bottom:25px;">
    <h2>
        Elite Rapid Scalper
        <button onclick="openScalperInfo()" style="background:#38bdf8;color:white;">i</button>
    </h2>

    <p style="color:#94a3b8;">
        Create a fast scalp setup with smart exit targets. Preview only. No live trade is placed.
    </p>

    <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-top:15px;">
        <div>
            <label>Symbol</label><br>
            <select id="scalper_symbol" style="width:100%; padding:10px; border-radius:8px;">
                <option value="BTC/USD">BTC/USD</option>
                <option value="ETH/USD">ETH/USD</option>
                <option value="XRP/USD">XRP/USD</option>
                <option value="SOL/USD">SOL/USD</option>
                <option value="ADA/USD">ADA/USD</option>
                <option value="DOGE/USD">DOGE/USD</option>
            </select>
        </div>

        <div>
            <label>Side</label><br>
            <select id="scalper_side" style="width:100%; padding:10px; border-radius:8px;">
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
            </select>
        </div>

        <div>
            <label>Amount USD</label><br>
            <input id="scalper_amount" type="number" value="25" min="5" style="width:100%; padding:10px; border-radius:8px;">
        </div>

        <div>
            <label>Target</label><br>
            <select id="scalper_target" style="width:100%; padding:10px; border-radius:8px;">
                <option value="0.5">0.5%</option>
                <option value="1.0">1.0%</option>
            </select>
        </div>

        <div>
            <label>Mode</label><br>
            <select id="scalper_mode" style="width:100%; padding:10px; border-radius:8px;">
                <option value="conservative">Conservative</option>
                <option value="momentum">Momentum</option>
                <option value="bounce">Bounce</option>
            </select>
        </div>
    </div>

    <button
        onclick="createRapidScalperPreview()"
        style="margin-top:15px; padding:12px 18px; border:none; border-radius:10px; background:#38bdf8; color:white; cursor:pointer;"
    >
        Create Rapid Scalper Preview
    </button>

    <button
        onclick="runRapidScalperPaper()"
        style="margin-top:10px; padding:10px; border-radius:8px; background:#22c55e; color:white; font-weight:bold;"
    >
        Run Paper Trade
    </button>

    <div id="rapid_scalper_message" style="margin-top:12px; color:#94a3b8;"></div>



        <div style="margin-top:14px; display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px;">
            <div>
                <div style="font-size:12px; color:#94a3b8;">Amount</div>
                <div id="active_scalper_amount" style="font-weight:700;">$25.00</div>
            </div>
            <div>
                <div style="font-size:12px; color:#94a3b8;">Target</div>
                <div id="active_scalper_target" style="font-weight:700;">0.50%</div>
            </div>
            <div>
                <div style="font-size:12px; color:#94a3b8;">Mode</div>
                <div id="active_scalper_mode" style="font-weight:700;">conservative</div>
            </div>
            <div>
                <div style="font-size:12px; color:#94a3b8;">Timer</div>
                <div id="active_scalper_timer" style="font-size:22px; font-weight:900; color:#22c55e;">45s</div>
            </div>
        </div>
    </div>

    <div id="rapid_scalper_active_trade" style="display:none; margin-top:15px; padding:18px; border-radius:16px; background:#020617; border:1px solid #22c55e; color:#e5e7eb;">
        <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
            <div>
                <div style="font-size:13px; color:#94a3b8;">Live Paper Scalp</div>
                <div id="active_scalper_title" style="font-size:20px; font-weight:900; color:#ffffff;">BTC/USD BUY</div>
            </div>
            <div id="active_scalper_status" style="padding:7px 12px; border-radius:999px; background:#14532d; color:#86efac; font-weight:900;">
                RUNNING
            </div>
        </div>

        <div style="margin-top:16px; display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:12px;">
            <div>
                <div style="font-size:12px; color:#94a3b8;">Amount</div>
                <div id="active_scalper_amount" style="font-size:17px; font-weight:800;">$0.00</div>
            </div>
            <div>
                <div style="font-size:12px; color:#94a3b8;">Entry Price</div>
                <div id="active_scalper_entry" style="font-size:17px; font-weight:800;">$0.0000</div>
            </div>
            <div>
                <div style="font-size:12px; color:#94a3b8;">Current Price</div>
                <div id="active_scalper_current" style="font-size:17px; font-weight:800;">$0.0000</div>
            </div>
            <div>
                <div style="font-size:12px; color:#94a3b8;">Target</div>
                <div id="active_scalper_target" style="font-size:17px; font-weight:800;">0.50%</div>
            </div>
            <div>
                <div style="font-size:12px; color:#94a3b8;">Mode</div>
                <div id="active_scalper_mode" style="font-size:17px; font-weight:800;">conservative</div>
            </div>
            <div>
                <div style="font-size:12px; color:#94a3b8;">Timer</div>
                <div id="active_scalper_timer" style="font-size:24px; font-weight:900; color:#22c55e;">45s</div>
            </div>
        </div>

        <div style="margin-top:18px; padding:14px; border-radius:12px; background:#0f172a; border:1px solid #1e293b;">
            <div style="font-size:12px; color:#94a3b8;">Live Profit / Loss</div>
            <div id="active_scalper_pnl" style="font-size:28px; font-weight:950; color:#22c55e;">$0.00 / 0.00%</div>
        </div>
    </div>

    <h3 style="margin-top:25px;">Recent Rapid Scalper Setups</h3>

    <div id="rapid_scalper_history" style="margin-top:10px; color:#94a3b8;">
        Loading...
    </div>
</div>

<section class="market-candles-section">
    <div class="section-header">
        <div>
            <h2>Live Market Charts</h2>
            <p>Track three live candlestick charts side by side. Each chart can monitor a different coin.</p>

    <label class="timeframe-sync-toggle">
        <input type="checkbox" id="syncTimeframesToggle">
        Sync timeframes
    </label>

        </div>
    </div>

    <div class="triple-candle-grid">

        <div class="candle-card">
            <div class="candle-card-header">

                <div class="chart-title-row">
                    <h3>Chart 1</h3>
                    <span id="chart1LivePrice" class="live-price-badge">$--</span>
                </div>


                <select id="chart-symbol-1" class="chart-symbol-select">
                    <option value="BTC/USD">BTC/USD</option>
                    <option value="ETH/USD">ETH/USD</option>
                    <option value="XRP/USD">XRP/USD</option>
                    <option value="SOL/USD">SOL/USD</option>
                    <option value="ADA/USD">ADA/USD</option>
                    <option value="DOGE/USD">DOGE/USD</option>
                    <option value="HBAR/USD">HBAR/USD</option>
                    <option value="XLM/USD">XLM/USD</option>
                    <option value="ICP/USD">ICP/USD</option>
                </select>
            </div>

            <div class="chart-container">
                <div class="chart-controls">
                    <select id="chart1Timeframe" class="chart-select">
                        <option value="1m">1m</option>
                        <option value="5m" selected>5m</option>
                        <option value="15m">15m</option>
                        <option value="30m">30m</option>
                        <option value="1h">1h</option>
                        <option value="4h">4h</option>
                        <option value="1d">1d</option>
                    </select>
            <div class="ema-toggle-row">
                <label><input type="checkbox" id="chart1Ema9Toggle" checked> EMA 9</label>
                <label><input type="checkbox" id="chart1Ema20Toggle" checked> EMA 20</label>
                <label><input type="checkbox" id="chart1Ema50Toggle" checked> EMA 50</label>
            </div>
                </div>

            <div class="chart-toolbar">
                <button type="button" class="chart-tool-btn" data-chart="1" data-action="reset">Reset</button>
                <button type="button" class="chart-tool-btn" data-chart="1" data-action="refresh">Refresh</button>
                <button type="button" class="chart-tool-btn" data-chart="1" data-action="fullscreen">Fullscreen</button>
                <button type="button" class="chart-tool-btn" data-chart="1" data-action="hide-emas">Hide EMAs</button>
            </div>
            <div id="chart1OhlcInfo" class="chart-ohlc-info">
                O: -- H: -- L: -- C: --
            </div>

            <div id="chart1CurrentOhlc" class="current-ohlc-info">
                Current: O -- H -- L -- C --
            </div>

                <div id="candle-chart-1" class="candle-chart-box"></div>
            </div>
        </div>

        <div class="candle-card">
            <div class="candle-card-header">

                <div class="chart-title-row">
                    <h3>Chart 2</h3>
                <span id="chart2LivePrice" class="live-price-badge">$--</span>
            </div>


                <select id="chart-symbol-2" class="chart-symbol-select">
                    <option value="ETH/USD">ETH/USD</option>
                    <option value="BTC/USD">BTC/USD</option>
                    <option value="XRP/USD">XRP/USD</option>
                    <option value="SOL/USD">SOL/USD</option>
                    <option value="ADA/USD">ADA/USD</option>
                    <option value="DOGE/USD">DOGE/USD</option>
                    <option value="HBAR/USD">HBAR/USD</option>
                    <option value="XLM/USD">XLM/USD</option>
                    <option value="ICP/USD">ICP/USD</option>
                </select>
            </div>

            <div class="chart-container">
                <div class="chart-controls">
                    <select id="chart2Timeframe" class="chart-select">
                        <option value="1m">1m</option>
                        <option value="5m" selected>5m</option>
                        <option value="15m">15m</option>
                        <option value="30m">30m</option>
                        <option value="1h">1h</option>
                        <option value="4h">4h</option>
                        <option value="1d">1d</option>
                    </select>

            <div class="ema-toggle-row">
                <label><input type="checkbox" id="chart2Ema9Toggle" checked> EMA 9</label>
                <label><input type="checkbox" id="chart2Ema20Toggle" checked> EMA 20</label>
                <label><input type="checkbox" id="chart2Ema50Toggle" checked> EMA 50</label>
            </div>
                </div>

            <div class="chart-toolbar">
                <button type="button" class="chart-tool-btn" data-chart="2" data-action="reset">Reset</button>
                <button type="button" class="chart-tool-btn" data-chart="2" data-action="refresh">Refresh</button>
                <button type="button" class="chart-tool-btn" data-chart="2" data-action="fullscreen">Fullscreen</button>
                <button type="button" class="chart-tool-btn" data-chart="2" data-action="hide-emas">Hide EMAs</button>
            </div>
            <div id="chart2OhlcInfo" class="chart-ohlc-info">
                O: -- H: -- L: -- C: --
            </div>

            <div id="chart2CurrentOhlc" class="current-ohlc-info">
                Current: O -- H -- L -- C --
            </div>

                <div id="candle-chart-2" class="candle-chart-box"></div>
            </div>
        </div>

        <div class="candle-card">
            <div class="candle-card-header">

                <div class="chart-title-row">
                    <h3>Chart 3</h3>
                    <span id="chart3LivePrice" class="live-price-badge">$--</span>
            </div>


                <select id="chart-symbol-3" class="chart-symbol-select">
                    <option value="XRP/USD">XRP/USD</option>
                    <option value="BTC/USD">BTC/USD</option>
                    <option value="ETH/USD">ETH/USD</option>
                    <option value="SOL/USD">SOL/USD</option>
                    <option value="ADA/USD">ADA/USD</option>
                    <option value="DOGE/USD">DOGE/USD</option>
                    <option value="HBAR/USD">HBAR/USD</option>
                    <option value="XLM/USD">XLM/USD</option>
                    <option value="ICP/USD">ICP/USD</option>
                </select>
            </div>

            <div class="chart-container">
                <div class="chart-controls">
                    <select id="chart3Timeframe" class="chart-select">
                        <option value="1m">1m</option>
                        <option value="5m" selected>5m</option>
                        <option value="15m">15m</option>
                        <option value="30m">30m</option>
                        <option value="1h">1h</option>
                        <option value="4h">4h</option>
                        <option value="1d">1d</option>
                    </select>

            <div class="ema-toggle-row">
                <label><input type="checkbox" id="chart3Ema9Toggle" checked> EMA 9</label>
                <label><input type="checkbox" id="chart3Ema20Toggle" checked> EMA 20</label>
                <label><input type="checkbox" id="chart3Ema50Toggle" checked> EMA 50</label>
            </div>
                </div>

            <div class="chart-toolbar">
                <button type="button" class="chart-tool-btn" data-chart="3" data-action="reset">Reset</button>
                <button type="button" class="chart-tool-btn" data-chart="3" data-action="refresh">Refresh</button>
                <button type="button" class="chart-tool-btn" data-chart="3" data-action="fullscreen">Fullscreen</button>
                <button type="button" class="chart-tool-btn" data-chart="3" data-action="hide-emas">Hide EMAs</button>
            </div>

            <div id="chart3OhlcInfo" class="chart-ohlc-info">
                O: -- H: -- L: -- C: --
            </div>

            <div id="chart3CurrentOhlc" class="current-ohlc-info">
                Current: O -- H -- L -- C --
            </div>

                <div id="candle-chart-3" class="candle-chart-box"></div>
            </div>
        </div>

    </div>
</section>
    <script>

        const savedUser = localStorage.getItem("bot_username");
        const savedToken = localStorage.getItem("bot_token");

        if (!savedUser || !savedToken) {{
            window.location.href = "/login";
       }}

        function logout() {{
            localStorage.removeItem("bot_username");
            localStorage.removeItem("bot_token");
            window.location.href = "/login";
       }}

async function createRapidScalperPreview() {{
    const payload = {{
        symbol: document.getElementById("scalper_symbol").value,
        side: document.getElementById("scalper_side").value,
        amount_usd: parseFloat(document.getElementById("scalper_amount").value),
        scalp_target_percent: parseFloat(document.getElementById("scalper_target").value),
        mode: document.getElementById("scalper_mode").value
    }};

    const res = await fetch("/elite/rapid-scalper/preview", {{
        method: "POST",
        headers: {{
            "Content-Type": "application/json",
            "x-plan": "elite"
        }},
        body: JSON.stringify(payload)
    }});

    const data = await res.json();

    const msg = document.getElementById("rapid_scalper_message");

    if (!res.ok) {{
        msg.innerText = data.detail || "Request failed.";
        return;
    }}

    msg.innerText = "Preview created successfully.";

    loadRapidScalperHistory();
}}

    let rapidScalperTimer = null;
    async function runRapidScalperPaper() {{
        const payload = {{
            symbol: document.getElementById("scalper_symbol").value,
            side: document.getElementById("scalper_side").value,
            amount_usd: parseFloat(document.getElementById("scalper_amount").value),
            scalp_target_percent: parseFloat(document.getElementById("scalper_target").value),
            mode: document.getElementById("scalper_mode").value
        }};

        const activeBox = document.getElementById("rapid_scalper_active_trade");
        const title = document.getElementById("active_scalper_title");
        const status = document.getElementById("active_scalper_status");
        const amount = document.getElementById("active_scalper_amount");
        const entry = document.getElementById("active_scalper_entry");
        const current = document.getElementById("active_scalper_current");
        const target = document.getElementById("active_scalper_target");
        const mode = document.getElementById("active_scalper_mode");
        const timer = document.getElementById("active_scalper_timer");
        const pnlBox = document.getElementById("active_scalper_pnl");
        const msg = document.getElementById("rapid_scalper_message");

        activeBox.style.display = "block";
        title.innerText = payload.symbol + " " + payload.side.toUpperCase();
        status.innerText = "OPENING";
        status.style.background = "#854d0e";
        status.style.color = "#fef3c7";
        amount.innerText = "$" + Number(payload.amount_usd || 0).toFixed(2);
        entry.innerText = "Loading...";
        current.innerText = "Loading...";
        target.innerText = Number(payload.scalp_target_percent || 0).toFixed(2) + "%";
        mode.innerText = payload.mode;
        timer.innerText = "Opening...";
        timer.style.color = "#facc15";
        pnlBox.innerText = "$0.00 / 0.00%";
        pnlBox.style.color = "#22c55e";
        msg.innerText = "";

        if (rapidScalperTimer) {{
            clearInterval(rapidScalperTimer);
            rapidScalperTimer = null;
        }}

        const res = await fetch("/elite/rapid-scalper/run-paper", {{
            method: "POST",
            headers: {{
                "Content-Type": "application/json",
                "x-plan": "elite"
            }},
            body: JSON.stringify(payload)
        }});

        const data = await res.json();

        if (!res.ok) {{
            msg.innerHTML = "Error: " + (data.detail || "Paper trade failed.");
            status.innerText = "FAILED";
            status.style.background = "#7f1d1d";
            status.style.color = "#fecaca";
            return;
        }}

        const entryPrice = Number(data.entry_price || 0);

        if (!entryPrice || entryPrice <= 0) {{
            msg.innerText = "Error: Entry price missing. Cannot calculate live PnL.";
            status.innerText = "FAILED";
            status.style.background = "#7f1d1d";
            status.style.color = "#fecaca";
            return;
        }}

        let currentPrice = entryPrice;
        let secondsLeft = 45;
        const priceSymbol = payload.symbol.replace("/", "-");

        entry.innerText = "$" + entryPrice.toFixed(4);
        current.innerText = "$" + currentPrice.toFixed(4);

        status.innerText = "RUNNING";
        status.style.background = "#14532d";
        status.style.color = "#86efac";
        timer.innerText = secondsLeft + "s";
        timer.style.color = "#22c55e";

        rapidScalperTimer = setInterval(async function () {{
            secondsLeft -= 1;

            try {{
                const priceRes = await fetch("/market/live-price/" + priceSymbol);
                const priceData = await priceRes.json();

                if (priceRes.ok && priceData.price) {{
                    currentPrice = Number(priceData.price);
                }}
            }} catch (error) {{
                console.error("Live price update failed:", error);
            }}

            let pnlPercent = 0;

            if (payload.side === "buy") {{
                pnlPercent = ((currentPrice - entryPrice) / entryPrice) * 100;
            }} else {{
                pnlPercent = ((entryPrice - currentPrice) / entryPrice) * 100;
            }}

            const pnlUsd = Number(payload.amount_usd || 0) * (pnlPercent / 100);
            const pnlColor = pnlUsd >= 0 ? "#22c55e" : "#ef4444";
            const prefix = pnlUsd >= 0 ? "+" : "";

            current.innerText = "$" + currentPrice.toFixed(4);
            timer.innerText = secondsLeft + "s";
            timer.style.color = pnlColor;
            pnlBox.style.color = pnlColor;
            pnlBox.innerText = prefix + "$" + pnlUsd.toFixed(2) + " / " + prefix + pnlPercent.toFixed(2) + "%";

            if (secondsLeft <= 0) {{
                clearInterval(rapidScalperTimer);
                rapidScalperTimer = null;

                status.innerText = pnlUsd >= 0 ? "CLOSED WIN" : "CLOSED LOSS";
                status.style.background = pnlUsd >= 0 ? "#14532d" : "#7f1d1d";
                status.style.color = pnlUsd >= 0 ? "#86efac" : "#fecaca";
                timer.innerText = "Closed";

                loadRapidScalperHistory();
            }}
        }}, 1000);
    }}

    async function loadRapidScalperHistory() {{
        try {{
            const res = await fetch("/elite/rapid-scalper/history", {{
                headers: {{
                    "x-plan": "elite"
                }}
            }});

            const text = await res.text();

            let data;
            try {{
                data = JSON.parse(text);
            }} catch {{
                console.error("Non-JSON response:", text);
                document.getElementById("rapid_scalper_history").innerText = "Error loading data.";
                return;
            }}

            const box = document.getElementById("rapid_scalper_history");

            if (!res.ok) {{
                box.innerText = data.detail || "Could not load Rapid Scalper history.";
                return
            }}

            if (!data.length) {{
                box.innerText = "No Rapid Scalper setups yet.";
                return;

            }}

            box.innerHTML = data.map(item => `
            <div style="
            padding:10px;
            border:1px solid #334155;
            border-radius:10px;
            margin-bottom:8px;
            background:#020617;
            ">
            <strong>${{item.symbol}}</strong>
            |
            ${{item.side.toUpperCase()}}
            |
            $${{item.amount_usd}}
            |
            Target ${{item.scalp_target_percent}}%
            |
            ${{item.mode}}
            <br>
            <span style="font-size:12px;color:#64748b;">
            ${{item.status}} • ${{item.created_at}}
            </span>
            </div>
            `).join("");

        }} catch (err) {{
            console.error(err);
            document.getElementById("rapid_scalper_history").innerText = "Failed to load.";
        }}
    }}

    async function loadBotStatus() {{
        const res = await fetch('/bot-control/{username}');
        const data = await res.json();

        const status = document.getElementById('bot_status');
        const dot = document.getElementById('bot_dot');
        const text = document.getElementById('bot_status_text');

        if (data.bot_enabled === true) {{
            status.innerText = 'Auto Opportunity Bot: RUNNING';
            status.style.color = '#22c55e';

            text.innerText = 'RUNNING';
            dot.style.background = '#22c55e';
            dot.style.boxShadow = '0 0 14px rgba(34,197,94,1)';
       }} else {{
            status.innerText = 'Auto Opportunity Bot: STOPPED';
            status.style.color = '#ef4444';

            text.innerText = 'STOPPED';
            dot.style.background = '#ef4444';
            dot.style.boxShadow = '0 0 14px rgba(239,68,68,1)';
       }}
    }}
    // loadRapidScalperHistory();

    async function startBot() {{
        await fetch('/bot-control/{username}/start', {{
            method: 'POST'
       }});

        loadBotStatus();
   }}

    async function stopBot() {{
        await fetch('/bot-control/{username}/stop', {{
            method: 'POST'
       }});

        loadBotStatus();
   }}

    let latestDashboardCash = 0;
    let latestBotAllocationTotal = 0;
    let latestAssetBots = [];


    async function loadDashboard() {{
        const res = await fetch('/dashboard/{username}');
        const data = await res.json();
        await updateProfitTicker(data);

        animateValue('equity', data.equity);
        document.getElementById('cash').innerText = '$' + data.cash.toFixed(2);
        document.getElementById('position_value').innerText = '$' + Number(data.position_value || 0).toFixed(2);

        const pnlEl = document.getElementById('pnl');
        const pnlSign = data.pnl >= 0 ? '+' : '';
        pnlEl.innerText = pnlSign + '$' + data.pnl.toFixed(2) + ' (' + data.pnl_percent.toFixed(2) + '%)';
        pnlEl.className = 'value ' + (data.pnl >= 0 ? 'profit' : 'loss');

        document.getElementById('open_positions').innerText = data.open_positions;

        latestDashboardCash = Number(data.cash || 0);

        const availableToAllocateEl = document.getElementById('available_to_allocate');
        if (availableToAllocateEl) {{
            const remainingAllocatable = latestDashboardCash - latestBotAllocationTotal;
            availableToAllocateEl.innerText = '$' + Math.max(remainingAllocatable, 0).toFixed(2);
        }}

        const tbody = document.getElementById('positions');
        tbody.innerHTML = '';

        for (const [symbol, pos] of Object.entries(data.positions)) {{
                    const row = document.createElement('tr');

            row.innerHTML = `
                <td>${{symbol}}</td>
                <td>${{pos.entry}}</td>
                <td>${{pos.amount}}</td>
                <td>${{pos.peak ?? '-'}}</td>
                <td>${{pos.partial_taken === true ? 'Yes' : 'No'}}</td>
                <td><span class="status">Active</span></td>
            `;

            tbody.appendChild(row);
        }}
    }}

    async function updateProfitTicker(data) {{
        const content = document.getElementById("profit_ticker_content");
        const clone = document.getElementById("profit_ticker_content_clone");

        if (!content || !clone) {{
            return;
        }}

        const pnlClass = data.pnl >= 0 ? "ticker-profit" : "ticker-loss";
        const pnlSign = data.pnl >= 0 ? "+" : "";

        const tradeEvents = await loadTradeTickerEvents();

        const html = `
            <span>Equity: <strong>$${{data.equity.toFixed(2)}}</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            <span>Cash: <strong>$${{data.cash.toFixed(2)}}</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            <span>PnL: <strong class="${{pnlClass}}">${{pnlSign}}$${{data.pnl.toFixed(2)}} (${{data.pnl_percent.toFixed(2)}}%)</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            <span>Open Positions: <strong>${{data.open_positions}}</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            <span>Bot Feed: <strong>LIVE</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            ${{tradeEvents}}
            <span>Risk Engine: <strong>ACTIVE</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;

        `;

        content.innerHTML = html;
        clone.innerHTML = html;
        }}

    async function loadTradeTickerEvents() {{
        const res = await fetch('/trade-history/{username}');
        const trades = await res.json();

        if (!Array.isArray(trades) || trades.length === 0) {{
            return "";
        }}

        return trades.slice(0, 5).map(t => {{
            const pnl = Number(t.pnl || 0);
            const resultClass = pnl >= 0 ? "ticker-profit" : "ticker-loss";
            const sign = pnl >= 0 ? "+" : "";

            return `
                <span>TRADE: <strong>${{t.symbol || "N/A"}}</strong></span>
                &nbsp;
                <span class="${{resultClass}}">${{sign}}$${{pnl.toFixed(2)}}</span>
                &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            `;
        }}).join("");
    }}



    function animateValue(id, target) {{
        const el = document.getElementById(id);
        const start = parseFloat(el.innerText.replace('$','')) || 0;
        const duration = 400;
        const startTime = performance.now();

        function update(now) {{
            const progress = Math.min((now - startTime) / duration, 1);
            const value = start + (target - start) * progress;
            el.innerText = '$' + value.toFixed(2);

            if (progress < 1) {{
                requestAnimationFrame(update);
            }}
        }}

        requestAnimationFrame(update);
    }}

async function loadEquityChart() {{
    const res = await fetch('/equity-history/{username}');
    const points = await res.json();

    const canvas = document.getElementById('equity_chart');

    if (!canvas) {{
        return;
    }}


    const ctx = canvas.getContext('2d');

    ctx.clearRect(0, 0, canvas.width, canvas.height);


    const unique = [];
    let lastEquity = null;

    for (const p of points) {{
        if (p.equity !== lastEquity) {{
            unique.push(p);
            lastEquity = p.equity;
        }}
    }}

    if (unique.length < 2) {{
        ctx.fillStyle = '#94a3b8';
        ctx.font = '16px Arial';
        ctx.fillText('No meaningful equity movement yet.', 30, 40);
        return;
    }}

    const equities = unique.map(p => p.equity);
    const min = Math.min(...equities);
    const max = Math.max(...equities);
    const range = max - min || 1;

    const padding = 35;
    const width = canvas.width;
    const height = canvas.height;

    ctx.fillStyle = '#020617';
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 1;

    for (let i = 1; i <= 4; i++) {{
        const y = padding + (i / 5) * (height - padding * 2);
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke()
    }}

    const coords = unique.map((p, i) => {{
        const x = padding + (i / (unique.length - 1)) * (width - padding * 2);
        const y = height - padding - ((p.equity - min) / range) * (height - padding * 2);
        return {{ x, y, equity: p.equity, pnl: p.pnl }};
    }});

    const last = coords[coords.length - 1];
    const first = coords[0];
    const isProfit = last.equity >= first.equity;

    const lineColor = isProfit ? '#22c55e' : '#ef4444';

    ctx.beginPath();
    ctx.moveTo(coords[0].x, coords[0].y);

    for (let i = 1; i < coords.length - 1; i++) {{
        const midX = (coords[i].x + coords[i + 1].x) / 2;
        const midY = (coords[i].y + coords[i + 1].y) / 2;
        ctx.quadraticCurveTo(coords[i].x, coords[i].y, midX, midY);
    }}

    ctx.lineTo(last.x, last.y);

    ctx.shadowColor = lineColor;
    ctx.shadowBlur = 14;
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 3;
    ctx.stroke();

    ctx.shadowBlur = 0;

    const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
    gradient.addColorStop(0, isProfit ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)');
    gradient.addColorStop(1, 'rgba(2,6,23,0)');

    ctx.lineTo(width - padding, height - padding);
    ctx.lineTo(padding, height - padding);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(last.x, last.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.shadowColor = lineColor;
    ctx.shadowBlur = 18;
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.fillStyle = '#e5e7eb';
    ctx.font = '14px Arial';
    ctx.fillText('Equity: $' + last.equity.toFixed(2), padding, 22);

    ctx.fillStyle = isProfit ? '#22c55e' : '#ef4444';
    ctx.fillText('PnL: $' + unique[unique.length - 1].pnl.toFixed(2), padding + 140, 22);

    ctx.fillStyle = '#64748b';
    ctx.font = '12px Arial';
    ctx.fillText('$' + max.toFixed(2), width - 95, padding);
    ctx.fillText('$' + min.toFixed(2), width - 95, height - padding)
}}

    async function loadTradeHistory() {{
        const res = await fetch('/trade-history/{username}');
        const trades = await res.json();

        const tbody = document.getElementById('trade_history');
        tbody.innerHTML = '';

        for (const trade of trades.reverse()) {{
            const row = document.createElement('tr');

            const pnl = parseFloat(trade.pnl || 0);
            const resultColor = pnl >= 0 ? '#22c55e' : '#ef4444';

            row.innerHTML = `
                <td>${{trade.symbol}}</td>
                <td>${{trade.entry}}</td>
                <td>${{trade.exit}}</td>
                <td>${{trade.amount}}</td>
                <td>${{trade.score}}</td>
                <td>${{trade.prob}}</td>
                <td style="color:${{resultColor}};">${{pnl.toFixed(4)}}</td>
                <td>${{trade.result}}</td>
            `;

            tbody.appendChild(row);
        }}
    }}

    async function loadSettings() {{
        const res = await fetch('/settings/{username}');
        const data = await res.json();

        document.getElementById('risk_percent').value =
            data.risk_percent;

        document.getElementById('max_positions').value =
            data.max_positions;

        document.getElementById('stop_loss_percent').value =
            data.stop_loss_percent;

        document.getElementById('partial_take_profit_percent').value =
            data.partial_take_profit_percent;

        document.getElementById('trailing_stop_percent').value =
            data.trailing_stop_percent;

        document.getElementById('bot_mode').value =
            data.bot_mode;
    }}

    async function saveSettings() {{
        const settings = {{
            risk_percent:
                parseFloat(document.getElementById('risk_percent').value),

            max_positions:
                parseInt(document.getElementById('max_positions').value),

            stop_loss_percent:
                parseFloat(document.getElementById('stop_loss_percent').value),

            partial_take_profit_percent:
                parseFloat(document.getElementById('partial_take_profit_percent').value),

            trailing_stop_percent:
                parseFloat(document.getElementById('trailing_stop_percent').value),

            bot_mode:
                document.getElementById('bot_mode').value
        }};

        await fetch('/settings/{username}', {{
            method: 'POST',
            headers: {{
                'Content-Type': 'application/json'
            }},
            body: JSON.stringify(settings)
        }});

        document.getElementById('settings_status').innerText =
        'Settings saved';
    }}

    async function loadBotLogs() {{
        const res = await fetch('/bot-logs/{username}');
        const logs = await res.json();

        const box = document.getElementById('bot_logs');
        if (!box) return;

        if (!Array.isArray(logs) || logs.length === 0) {{
            box.innerText = 'No logs found yet.';
            return;
        }}


        const formatted = logs.slice(-80).map(line => {{
            return '> ' + line;
        }}).join('\\n');

        box.innerText = formatted;
        box.scrollTop = box.scrollHeight;

    }}

    function toggleBotConsole() {{
        const panel = document.getElementById("bot_console_panel");
        const arrow = document.getElementById("bot_console_arrow");

        if (!panel || !arrow) return;

        const isOpen = panel.classList.contains("open");

        if (isOpen) {{
            panel.classList.remove("open");
            arrow.innerText = "▼";
            localStorage.setItem("bot_console_open", "false");
        }} else {{
            panel.classList.add("open");
            arrow.innerText = "▲";
            localStorage.setItem("bot_console_open", "false");
        }}
    }}

    function restoreBotConsoleState() {{
        const panel = document.getElementById("bot_console_panel");
        const arrow = document.getElementById("bot_console_arrow");

        if (!panel || !arrow) return;

        const saved = localStorage.getItem("bot_console_open");

        if (saved === "false") {{
            panel.classList.remove("open");
            arrow.innerText = "▼";
        }} else {{
            panel.classList.add("open");
            arrow.innerText = "▲";
        }}
    }}

    async function loadBilling() {{
        const res = await fetch('/billing/{username}');
        const data = await res.json();

        document.getElementById('billing_plan').innerText =
            data.plan.toUpperCase();

        document.getElementById('billing_status').innerText =
            data.subscription_status.toUpperCase();

        const f = data.features;

        document.getElementById('billing_features').innerHTML = `
            Max Bots: ${{f.max_bots}}<br>
            Max Positions: ${{f.max_positions}}<br>
            Paper Trading: ${{f.paper_trading ? 'Yes' : 'No'}}<br>
            Live Trading: ${{f.live_trading ? 'Yes' : 'No'}}<br>
            Advanced AI: ${{f.advanced_ai ? 'Yes' : 'No'}}
        `;
    }}

    async function changePlan(plan) {{
    if (plan === 'basic') {{
        const res = await fetch('/billing/{username}/checkout/basic', {{
            method: 'POST'
        }});

        const data = await res.json();

        if (data.checkout_url) {{
            window.location.href = data.checkout_url;
            return;
        }}

        alert(data.error || 'Checkout failed');
        return;
    }}

    await fetch('/billing/{username}/set-plan/' + plan, {{
        method: 'POST'
    }});

    loadBilling();
}}

    let loadBotsRunning = false;
    let latestAssetPositions = [];
    let refreshBotPnlRunning = false;

    async function refreshBotPnlCells() {{
        if (refreshBotPnlRunning) {{
            return;
        }}

        refreshBotPnlRunning = true;

        try {{

            if (!latestAssetPositions || latestAssetPositions.length === 0) {{
                return;
            }}


        for (const position of latestAssetPositions) {{
            const marketSymbol = position.symbol.replace("/", "-");

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 2500);

            let priceData = null;

            try {{
                const priceRes = await fetch('/market/live-price/' + marketSymbol, {{
                    signal: controller.signal
                }});
                priceData = await priceRes.json();
            }} catch (error) {{
                console.error("PnL price refresh timed out or failed", error);
                continue;
            }} finally {{
                clearTimeout(timeoutId);
            }}


            if (priceData.detail || priceData.price === null) {{
                continue;
            }}

            const currentPrice = Number(priceData.price || 0);
            const entryPrice = Number(position.entry_price || 0);
            const amount = Number(position.amount || 0);
            const costBasis = entryPrice * amount;
            const currentValue = currentPrice * amount;
            const pnl = currentValue - costBasis;
            const pnlPercent = costBasis > 0 ? (pnl / costBasis) * 100 : 0;
            const pnlColor = pnl >= 0 ? "#22c55e" : "#ef4444";

            const pnlCell = document.getElementById("bot_change_usd_" + position.bot_id);
            const pnlPercentCell = document.getElementById("bot_change_percent_" + position.bot_id);
            const lastUpdateCell = document.getElementById("bot_last_update_" + position.bot_id);

            if (pnlCell) {{
                pnlCell.innerText = (pnl >= 0 ? "+$" : "-$") + Math.abs(pnl).toFixed(2);
                pnlCell.style.color = pnlColor;
            }}

            if (pnlPercentCell) {{
                pnlPercentCell.innerText = (pnlPercent >= 0 ? "+" : "") + pnlPercent.toFixed(2) + "%";
                pnlPercentCell.style.color = pnlColor;
            }}

            if (lastUpdateCell) {{
                lastUpdateCell.innerText = "Updated " + new Date().toLocaleTimeString();
            }}
        }}

        }} finally {{
            refreshBotPnlRunning = false;
        }}
    }}

    let refreshBotStateRunning = false;

    async function refreshBotStateCells() {{
        if (refreshBotStateRunning) {{
            return;
        }}

        refreshBotStateRunning = true;

        try {{
            const [botRes, positionRes] = await Promise.all([
                fetch('/bots/{username}'),
                fetch('/asset-bot-positions/{username}')
            ]);
            const [bots, positions] = await Promise.all([
                botRes.json(),
                positionRes.json()
            ]);

            latestAssetBots = bots;
            latestAssetPositions = positions;

            for (const bot of bots) {{
                const positionsCell = document.getElementById("bot_positions_" + bot.id);
                const closeButton = document.getElementById("bot_close_" + bot.id);
                const row = positionsCell ? positionsCell.closest("tr") : null;
                const statusCell = row ? row.querySelector(".status") : null;

                if (positionsCell) {{
                    positionsCell.innerText = String(bot.current_open_positions || 0) + " / " + String(bot.max_open_positions || 0);
                }}

                if (closeButton) {{
                    closeButton.style.display = Number(bot.current_open_positions || 0) > 0 ? "block" : "none";
                }}

                if (statusCell) {{
                    statusCell.innerText = bot.enabled === false ? "Paused" : "Active";
                }}

                const position = positions.find(item => item.bot_id === bot.id);
                if (!position) {{
                    const pnlCell = document.getElementById("bot_change_usd_" + bot.id);
                    const pnlPercentCell = document.getElementById("bot_change_percent_" + bot.id);

                    if (pnlCell) {{
                        pnlCell.innerText = "+$0.00";
                        pnlCell.style.color = "#22c55e";
                    }}

                    if (pnlPercentCell) {{
                        pnlPercentCell.innerText = "+0.00%";
                        pnlPercentCell.style.color = "#22c55e";
                    }}
                }}
            }}
        }} catch (error) {{
            console.error("Bot state refresh failed", error);
        }} finally {{
            refreshBotStateRunning = false;
        }}
    }}

    async function loadBots() {{
        if (loadBotsRunning) {{
            return;
        }}

        loadBotsRunning = true;

        try {{
            const res = await fetch('/bots/{username}');
            const bots = await res.json();
            latestAssetBots = bots;

            const positionRes = await fetch('/asset-bot-positions/{username}');
            const positions = await positionRes.json();
            latestAssetPositions = positions;

        const tbody = document.getElementById('my_bots');
        const newRows = document.createDocumentFragment();

        latestBotAllocationTotal = bots.reduce((total, bot) => {{
            return total + Number(bot.allocated_cash || 0);
        }}, 0);

        const availableToAllocateEl = document.getElementById('available_to_allocate');
        if (availableToAllocateEl) {{
            const remainingAllocatable = latestDashboardCash - latestBotAllocationTotal;
            availableToAllocateEl.innerText = '$' + Math.max(remainingAllocatable, 0).toFixed(2);
        }}

        if (bots.length === 0) {{
            tbody.innerHTML = `
                <tr>
                    <td colspan="12" style="color:#94a3b8;">
                        No bots created yet.
                    </td>
                </tr>
            `;
            return;
        }}

        for (const bot of bots) {{
            const row = document.createElement('tr');

            const marketSymbol = bot.symbol.replace("/", "-");
            let priceText = "Loading...";
            let changeUsdText = "Loading...";
            let changePercentText = "Loading...";
            let changeColor = "#94a3b8";
            let lastScanText = bot.last_scan || "Not scanned yet";

            try {{
                const priceRes = await fetch('/market/live-price/' + marketSymbol);
                const priceData = await priceRes.json();

                if (!priceData.detail && priceData.price !== null) {{
                    const position = positions.find(item => item.bot_id === bot.id);
                    const changeUsd = position ? Number(position.unrealized_pnl || 0) : 0;
                    const changePercent = position ? Number(position.unrealized_pnl_percent || 0) : 0;

                    priceText = "$" + Number(priceData.price).toLocaleString(undefined, {{
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 6
                    }});


                    changeUsdText = (changeUsd >= 0 ? "+$" : "-$") + Math.abs(changeUsd).toLocaleString(undefined, {{
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 6
                    }});

                    changePercentText = (changePercent >= 0 ? "+" : "") + changePercent.toFixed(2) + "%";
                    changeColor = changeUsd >= 0 ? "#22c55e" : "#ef4444";
                    lastScanText = new Date(priceData.timestamp).toLocaleTimeString();

                }} else {{
                    priceText = "Unsupported";
                    changeUsdText = "-";
                    changePercentText = "-";
                }}
            }} catch (error) {{
                priceText = "Unavailable";
                changeUsdText = "-";
                changePercentText = "-";
            }}

            const closePositionDisplay = Number(bot.current_open_positions || 0) > 0 ? "block" : "none";

            row.innerHTML = `
                <td>${{bot.name}}</td>
                <td>${{bot.symbol}}</td>
                <td>${{bot.strategy_name || 'Legacy default'}}</td>
                <td>${{bot.allocated_cash ? '$' + Number(bot.allocated_cash).toFixed(2) : 'Not set'}}</td>
                <td id="bot_price_${{bot.id}}">${{priceText}}</td>
                <td id="bot_change_usd_${{bot.id}}" style="color:${{changeColor}};">${{changeUsdText}}</td>
                <td id="bot_change_percent_${{bot.id}}" style="color:${{changeColor}};">${{changePercentText}}</td>
                <td><span class="status">${{bot.enabled === false ? 'Paused' : 'Active'}}</span></td>
                <td id="bot_positions_${{bot.id}}">${{bot.current_open_positions}} / ${{bot.max_open_positions}}</td>
                <td id="bot_last_update_${{bot.id}}">${{lastScanText}}</td>
                <td>${{bot.last_action}}</td>


                <td>
                    <div style="
                        display:flex;
                        flex-direction:column;
                        gap:4px;
                        min-width:90px;
                    ">


                    <button
                        onclick="viewBot('${{bot.id}}')"
                        style="
                        padding:5px 8px;
                        font-size:12px;
                        border:none;
                        border-radius:6px;
                        background:#38bdf8;
                        color:white;
                        cursor:pointer;
                        "
                    >
                        View
                    </button>


                    <button
                        onclick="${{bot.enabled === false ? `resumeBot('${{bot.id}}')` : `pauseBot('${{bot.id}}')`}}"
                        style="
                        padding:5px 8px;
                        font-size:12px;
                        border:none;
                        border-radius:6px;
                        background:#f59e0b;
                        color:white;
                        cursor:pointer;
                        "
                    >
                        ${{bot.enabled === false ? 'Resume' : 'Pause'}}
                    </button>


                    <button
                        id="bot_close_${{bot.id}}"
                        onclick="closePosition('${{bot.id}}')"
                        style="
                        padding:5px 8px;
                        font-size:12px;
                        border:none;
                        border-radius:6px;
                        background:#22c55e;
                        color:white;
                        cursor:pointer;
                        display:${{closePositionDisplay}};
                        "
                    >
                        Close
                    </button>

                    <button
                        onclick="deleteBot('${{bot.id}}')"
                        style="
                        padding:5px 8px;
                        font-size:12px;
                        border:none;
                        border-radius:6px;
                        background:#ef4444;
                        color:white;
                        cursor:pointer;
                        "
                    >
                        Delete
                    </button>

                    </div
                </td>
            `;

            newRows.appendChild(row);
        }}
        tbody.innerHTML = '';
        tbody.appendChild(newRows);

        }} finally {{
            loadBotsRunning = false;
        }}
    }}

    let refreshBotMarketRunning = false;

    async function refreshBotMarketCells() {{
        if (refreshBotMarketRunning) {{
            return;
        }}

        refreshBotMarketRunning = true;

        try {{
            const bots = latestAssetBots || [];

            await Promise.all(bots.map(async bot => {{
                const marketSymbol = bot.symbol.replace("/", "-");

                try {{
                    const priceRes = await fetch('/market/live-price/' + marketSymbol);
                    const priceData = await priceRes.json();

                    if (priceData.detail || priceData.price === null) {{
                        return;
                    }}

                    const priceCell = document.getElementById("bot_price_" + bot.id);
                    const lastUpdateCell = document.getElementById("bot_last_update_" + bot.id);

                    if (priceCell) {{
                        priceCell.innerText = "$" + Number(priceData.price).toLocaleString(undefined, {{
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 6
                        }});
                    }}

                    if (lastUpdateCell) {{
                        lastUpdateCell.innerText = "Updated " + new Date().toLocaleTimeString();
                    }}
                }} catch (error) {{
                    console.error("Bot market cell refresh failed", error);
                }}
            }}));
        }} finally {{
            refreshBotMarketRunning = false;
        }}
    }}

    async function createBot() {{
        const name = document.getElementById('new_bot_name').value || 'New Bot';
        const symbol = document.getElementById('new_bot_symbol').value || 'BTC/USD';
        const strategyId = document.getElementById('new_bot_strategy').value;
        const allocatedCash = parseFloat(document.getElementById('new_bot_allocated_cash').value || 0);
        const status = document.getElementById('bot_create_status');

        if (!strategyId) {{
            status.innerText = 'Choose a strategy before creating this bot';
            status.style.color = '#ef4444';
            document.getElementById('new_bot_strategy').focus();
            return;
        }}

        if (!allocatedCash || allocatedCash <= 0) {{
            status.innerText = 'Enter an allocated cash amount greater than $0';
            status.style.color = '#ef4444';
            return;
        }}

        const res = await fetch('/bots/{username}/create', {{
            method: 'POST',
            headers: {{
                'Content-Type': 'application/json'
            }},
            body: JSON.stringify({{
                name: name,
                symbol: symbol,
                strategy_id: strategyId,
                allocated_cash: allocatedCash,
                timeframe: '15m',
                risk_percent: 1.0
            }})
        }});

        const data = await res.json();

        if (data.error) {{
            status.innerText = data.error;
            status.style.color = '#ef4444';
            return;
        }}

        status.innerText = 'Bot created with $' + allocatedCash.toFixed(2) + ' allocated';
        status.style.color = '#22c55e';


        document.getElementById('new_bot_name').value = '';
        document.getElementById('new_bot_allocated_cash').value = '';

        await loadBots();
        await refreshBotStateCells();
        await refreshBotPnlCells();

        loadBots();
    }}

    async function deleteBot(botId) {{
        await fetch('/bots/{username}/' + botId, {{
            method: 'DELETE'
        }});

        loadBots();
    }}

    async function closePosition(botId) {{
        if (!confirm("Close this open position at the current market price?")) {{
            return;
        }}

        const res = await fetch('/asset-bot-close-position/{username}/' + botId, {{
            method: 'POST'
        }});

        const data = await res.json();

        if (data.error) {{
            alert(data.error);
            return;
        }}

        alert("Position closed. PnL: $" + Number(data.trade.pnl || 0).toFixed(2) + " (" + Number(data.trade.pnl_percent || 0).toFixed(2) + "%)");

        closeAssetBotDetail();
        loadBots();
    }}

    async function viewBot(botId) {{
        const bot = latestAssetBots.find(item => item.id === botId);

        if (!bot) {{
            alert("Bot details unavailable. Refresh and try again.");
            return;
        }}

        const positionRes = await fetch('/asset-bot-positions/{username}');
        const positions = await positionRes.json();
        const position = positions.find(item => item.bot_id === botId);

        let positionHtml = `
            <hr style="border:0;border-top:1px solid #334155;margin:14px 0;">
            <p><strong>Open Position:</strong> None</p>
        `;

        if (position) {{
            const entryPrice = Number(position.entry_price || 0);
            const currentPrice = Number(position.current_price || position.entry_price || 0);
            const currentValue = Number(position.current_value || position.allocated_cash || 0);
            const pnl = Number(position.unrealized_pnl || 0);
            const pnlPercent = Number(position.unrealized_pnl_percent || 0);

            positionHtml = `
                <hr style="border:0;border-top:1px solid #334155;margin:14px 0;">


                <p><strong>Open Position:</strong> ${{position.symbol}}</p>
                <p><strong>Entry Price:</strong> $${{entryPrice.toFixed(6)}}</p>
                <p><strong>Current Price:</strong> $${{currentPrice.toFixed(6)}}</p>
                <p><strong>Current Value:</strong> $${{currentValue.toFixed(2)}}</p>
                <p><strong>Unrealized PnL:</strong> $${{pnl.toFixed(2)}} (${{pnlPercent.toFixed(2)}}%)</p>
                <p><strong>Opened At:</strong> ${{position.opened_at || "-"}}</p>
                <p><strong>Last Checked:</strong> ${{position.last_checked_at || "Not checked yet"}}</p>
            `;
        }}

        document.getElementById("assetBotDetailTitle").innerText = bot.name || "Asset Bot";

        document.getElementById("assetBotDetailContent").innerHTML = `
            <p><strong>Pair:</strong> ${{bot.symbol}}</p>
            <p><strong>Allocated Cash:</strong> $${{Number(bot.allocated_cash || 0).toFixed(2)}}</p>
            <p><strong>Status:</strong> ${{bot.enabled === false ? "Paused" : "Active"}}</p>
            <p><strong>Positions:</strong> ${{bot.current_open_positions}} / ${{bot.max_open_positions}}</p>
            <p><strong>Last Scan:</strong> ${{bot.last_scan}}</p>
            <p><strong>Last Action:</strong> ${{bot.last_action}}</p>
            <p><strong>Created:</strong> ${{bot.created_at}}</p>
            ${{positionHtml}}
        `;

        document.getElementById("assetBotDetailModal").style.display = "flex";
    }}

    function closeAssetBotDetail() {{
        document.getElementById("assetBotDetailModal").style.display = "none";
    }}


    async function pauseBot(botId) {{
        await fetch('/bots/{username}/' + botId + '/pause', {{
            method: 'POST'
        }});

        loadBots();
    }}

    async function resumeBot(botId) {{
        await fetch('/bots/{username}/' + botId + '/resume', {{
            method: 'POST'
        }});

        loadBots();
    }}


    function toggleOpenTrades() {{
        const panel = document.getElementById('open_trades_panel');

        if (panel.style.display === 'none') {{
            panel.style.display = 'block';
        }} else {{
            panel.style.display = 'none';
        }}
    }}

    function toggleTradeHistory() {{
        const panel = document.getElementById('trade_history_panel');

        if (panel.style.display === 'none') {{
            panel.style.display = 'block';
        }} else {{
            panel.style.display = 'none';
        }}
    }}

    let latestStrategies = [];
    let currentStrategyMode = "balanced";

    const strategyPresets = {{
        conservative: {{ score: 72, ai: 0.65, stop: 1.5, target: 3, trailing: 1, cooldown: 4 }},
        balanced: {{ score: 60, ai: 0.50, stop: 2, target: 4, trailing: 1.5, cooldown: 2 }},
        aggressive: {{ score: 48, ai: 0.35, stop: 3, target: 6, trailing: 2.5, cooldown: 1 }}
    }};

    function escapeStrategyText(value) {{
        return String(value ?? "").replace(/[&<>"']/g, character => ({{
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
        }})[character]);
    }}

    function strategyFormValues() {{
        return {{
            name: document.getElementById("strategy_name").value.trim(),
            mode: currentStrategyMode,
            min_score: Number(document.getElementById("strategy_score").value),
            min_ai_probability: Number(document.getElementById("strategy_ai").value),
            stop_loss_percent: Number(document.getElementById("strategy_stop_loss").value),
            partial_take_profit_percent: Number(document.getElementById("strategy_take_profit").value),
            trailing_stop_percent: Number(document.getElementById("strategy_trailing").value),
            cooldown_hours: Number(document.getElementById("strategy_cooldown").value)
        }};
    }}

    function validateStrategyForm(showNameError = true) {{
        const values = strategyFormValues();
        const errors = [];
        if (showNameError && (values.name.length < 2 || values.name.length > 60)) errors.push("Enter a strategy name (2–60 characters).");
        if (values.min_score < 0 || values.min_score > 100) errors.push("Signal score must be 0–100.");
        if (values.min_ai_probability < 0 || values.min_ai_probability > 1) errors.push("AI confidence must be 0–1.");
        if (values.stop_loss_percent < 0.1 || values.stop_loss_percent > 25) errors.push("Stop loss must be 0.1–25%.");
        if (values.partial_take_profit_percent < 0.1 || values.partial_take_profit_percent > 100) errors.push("Take profit must be 0.1–100%.");
        if (values.trailing_stop_percent < 0.1 || values.trailing_stop_percent > 25) errors.push("Trailing stop must be 0.1–25%.");
        if (values.cooldown_hours < 0 || values.cooldown_hours > 168) errors.push("Cooldown must be 0–168 hours.");
        return errors;
    }}

    function updateStrategyPreview() {{
        const values = strategyFormValues();
        const name = values.name || currentStrategyMode.charAt(0).toUpperCase() + currentStrategyMode.slice(1) + " strategy";
        document.getElementById("strategy_preview_name").innerText = name;
        document.getElementById("strategy_preview_text").innerText =
            `Requires score ${{values.min_score}} and ${{Math.round(values.min_ai_probability * 100)}}% AI confidence. ` +
            `Exits at -${{values.stop_loss_percent}}% stop loss or +${{values.partial_take_profit_percent}}% target, ` +
            `with a ${{values.trailing_stop_percent}}% trailing stop and ${{values.cooldown_hours}}h cooldown.`;
        const errors = validateStrategyForm(false);
        document.getElementById("strategy_validation").innerText = errors[0] || "Controls are within safe limits.";
        document.getElementById("strategy_validation").style.color = errors.length ? "#fca5a5" : "#86efac";
        document.getElementById("strategy_save_button").disabled = errors.length > 0;
        document.getElementById("strategy_save_button").style.opacity = errors.length ? "0.55" : "1";
    }}

    function applyStrategyPreset(mode) {{
        const preset = strategyPresets[mode];
        if (!preset) return;
        currentStrategyMode = mode;
        document.getElementById("strategy_score").value = preset.score;
        document.getElementById("strategy_ai").value = preset.ai;
        document.getElementById("strategy_stop_loss").value = preset.stop;
        document.getElementById("strategy_take_profit").value = preset.target;
        document.getElementById("strategy_trailing").value = preset.trailing;
        document.getElementById("strategy_cooldown").value = preset.cooldown;
        document.querySelectorAll(".strategy-preset").forEach(button => {{
            const selected = button.dataset.mode === mode;
            button.style.borderColor = selected ? "#38bdf8" : "#334155";
            button.style.background = selected ? "rgba(56,189,248,.08)" : "#0f172a";
        }});
        updateStrategyPreview();
    }}

    async function loadStrategies() {{
        const tbody = document.getElementById("strategies");
        const selector = document.getElementById("new_bot_strategy");
        const previousSelection = selector ? selector.value : "";

        try {{
            const res = await fetch('/strategies/{username}');
            if (!res.ok) throw new Error("Unable to load strategies");
            latestStrategies = await res.json();
        }} catch (error) {{
            tbody.innerHTML = `<tr><td colspan="9" style="color:#fca5a5;">${{escapeStrategyText(error.message)}}</td></tr>`;
            return;
        }}

        document.getElementById("strategy_count").innerText = `${{latestStrategies.length}} saved`;
        tbody.innerHTML = '';

        if (selector) {{
            selector.innerHTML = '<option value="">Choose a strategy</option>';
            latestStrategies.forEach(strategy => {{
                const option = document.createElement("option");
                option.value = strategy.id;
                option.textContent = `${{strategy.name}} (${{strategy.mode}})`;
                selector.appendChild(option);
            }});
            if (latestStrategies.some(strategy => strategy.id === previousSelection)) selector.value = previousSelection;
            else if (latestStrategies.length === 1) selector.value = latestStrategies[0].id;
        }}

        if (latestStrategies.length === 0) {{
            tbody.innerHTML = '<tr><td colspan="9" style="color:#94a3b8;padding:18px;">No strategies yet. Choose a preset above and save your first strategy.</td></tr>';
            return;
        }}

        for (const strategy of latestStrategies) {{
            const row = document.createElement('tr');
            const assigned = Number(strategy.assigned_bot_count || 0);
            row.innerHTML = `
                <td><strong>${{escapeStrategyText(strategy.name)}}</strong></td>
                <td style="text-transform:capitalize;">${{escapeStrategyText(strategy.mode)}}</td>
                <td>${{Number(strategy.min_score)}} / ${{Math.round(Number(strategy.min_ai_probability) * 100)}}%</td>
                <td>-${{Number(strategy.stop_loss_percent)}}%</td>
                <td>+${{Number(strategy.partial_take_profit_percent)}}%</td>
                <td>${{Number(strategy.trailing_stop_percent)}}%</td>
                <td>${{Number(strategy.cooldown_hours)}}h</td>
                <td><span style="color:${{assigned ? '#38bdf8' : '#64748b'}};">${{assigned}}</span></td>
                <td><button type="button" ${{assigned ? 'disabled' : ''}} onclick="deleteStrategy('${{strategy.id}}')" style="padding:7px 10px;border:none;border-radius:7px;background:${{assigned ? '#334155' : '#ef4444'}};color:white;cursor:${{assigned ? 'not-allowed' : 'pointer'}};">${{assigned ? 'In use' : 'Delete'}}</button></td>
            `;
            tbody.appendChild(row);
        }}
    }}

    async function createStrategy() {{
        const status = document.getElementById("strategy_status");
        const button = document.getElementById("strategy_save_button");
        const errors = validateStrategyForm(true);
        if (errors.length) {{
            status.innerText = errors[0];
            status.style.color = "#fca5a5";
            return;
        }}

        button.disabled = true;
        button.innerText = "Saving…";
        status.innerText = "";
        try {{
            const res = await fetch('/strategies/{username}/create', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(strategyFormValues())
            }});
            const data = await res.json();
            if (!res.ok || data.error || data.detail) throw new Error(data.detail || data.error || "Unable to save strategy");
            status.innerText = `Saved “${{data.name}}”. Select it when creating a bot.`;
            status.style.color = "#86efac";
            document.getElementById("strategy_name").value = "";
            await loadStrategies();
            const selector = document.getElementById("new_bot_strategy");
            if (selector) selector.value = data.id;
            updateStrategyPreview();
        }} catch (error) {{
            status.innerText = error.message;
            status.style.color = "#fca5a5";
        }} finally {{
            button.disabled = false;
            button.innerText = "Save strategy";
        }}
    }}

    async function deleteStrategy(strategyId) {{
        const strategy = latestStrategies.find(item => item.id === strategyId);
        if (!strategy || Number(strategy.assigned_bot_count || 0) > 0) return;
        if (!confirm(`Delete strategy “${{strategy.name}}”?`)) return;

        const res = await fetch('/strategies/{username}/' + strategyId, {{method: 'DELETE'}});
        const data = await res.json();
        if (!res.ok || data.detail) {{
            const status = document.getElementById("strategy_status");
            status.innerText = data.detail || "Unable to delete strategy";
            status.style.color = "#fca5a5";
            return;
        }}
        await loadStrategies();
    }}
    function openDashboardBotInfo() {{
        const modal = document.getElementById("dashboardBotInfoModal");
        if (modal) {{
            modal.style.display = "flex";
        }}
    }}

    function closeDashboardBotInfo() {{
        const modal = document.getElementById("dashboardBotInfoModal");
        if (modal) {{
            modal.style.display = "none";
        }}
    }}

    function openStrategyInfo() {{
        document.getElementById("strategyInfoModal").style.display = "flex";
    }}

    function closeStrategyInfo() {{
        document.getElementById("strategyInfoModal").style.display = "none";
    }}

    function openScalperInfo() {{
        document.getElementById("scalperInfoModal").style.display = "flex";
    }}

    function closeScalperInfo() {{
        document.getElementById("scalperInfoModal").style.display = "none";
    }}



    loadDashboard();
    loadBots();


    loadBotStatus();
    loadTradeHistory();
    loadSettings();
    loadBotLogs();
    loadEquityChart();
    loadBilling();
    applyStrategyPreset('balanced');
    loadStrategies();
    // loadLiveMarketPrice();
    restoreBotConsoleState();
    // setInterval(loadLiveMarketPrice, 5000);


    setInterval(refreshBotStateCells, 1000);
    setInterval(loadBotStatus, 15000);
    setInterval(loadTradeHistory, 15000);
    setInterval(loadBotLogs, 3000);
    setInterval(loadBilling, 30000);
    // My Bots only refreshes after create/delete to prevent table flashing.
    setInterval(refreshBotMarketCells, 1000);
    setInterval(refreshBotPnlCells, 1000);

    setInterval(loadStrategies, 60000);
    loadEquityChart();


    </script>

    <div id="assetBotDetailModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:9999;justify-content:center;align-items:center;">
        <div style="background:#111827;padding:25px;border-radius:12px;max-width:520px;width:90%;color:white;border:1px solid #334155;">
            <button onclick="closeAssetBotDetail()" style="float:right;background:#ef4444;color:white;border:none;border-radius:6px;padding:6px 10px;cursor:pointer;">X</button>
            <h2 id="assetBotDetailTitle">Asset Bot</h2>
            <div id="assetBotDetailContent" style="color:#cbd5e1;line-height:1.7;"></div>
        </div>
    </div>


    <div id="dashboardBotInfoModal" style="
        display:none;
        position:fixed;
        top:0;
        left:0;
        width:100%;
        height:100%;
        background:rgba(0,0,0,0.7);
        z-index:9999;
        justify-content:center;
        align-items:center;
    ">

        <div style="
            background:#111827;
            padding:25px;
            border-radius:12px;
            max-width:600px;
            color:white;
        ">

            <button onclick="closeDashboardBotInfo()" style="float:right;">X</button>

            <h2>How to Use the Bot</h2>

            <h3>1. Start in Paper Mode</h3>

            <p>Use Paper mode first. This lets you test the bot with simulated funds before risking real money.</p>

            <h3>2. Configure Your Settings</h3>
            <p>Set your risk %, max positions, stop loss, partial take profit, and trailing stop. These control risk, exits, and profit protection.</p>

            <h3>3. Create or Select a Strategy</h3>
            <p>The bot uses your strategy rules to decide when a trade setup is strong enough. Strategy settings can include score, AI probability, stop loss, and take profit rules.</p>

            <h3>4. Start the Bot</h3>
            <p>Click Start Bot. The bot will scan market data, check indicators, evaluate AI confidence, and look for trades that match your settings.</p>

            <h3>5. Monitor Performance</h3>
            <p>Watch Equity, Cash, PnL, Open Positions, Open Trades, Trade History, Live Bot Console, and Performance Chart to see what the bot is doing.</p>

            <h3>6. Stop When Needed</h3>
            <p>Click Stop Bot to pause automation. This prevents the bot from opening new trades while you review settings or market conditions.</p>

            <h3>Important</h3>
            <p>The bot does not guarantee profit. It follows your settings and strategy rules. Market conditions can change quickly, and losses are possible.</p>

        </div>
    </div>

    <div id="strategyInfoModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:9999;justify-content:center;align-items:center;">

    <div style="background:#111827;padding:25px;border-radius:12px;max-width:650px;color:white;">

        <button onclick="closeStrategyInfo()" style="float:right;">X</button>

        <h2>How to Use Strategy Builder</h2>

        <h3>1. Strategy Name</h3>
        <p>
            Give your strategy a name so you can identify it later. This does not affect trading logic.
        </p>

        <h3>2. Min Score</h3>
        <p>
            This is the overall confidence score required before a trade is considered.
            Higher values = fewer but stronger trades.
            Lower values = more trades but higher risk.
        </p>

        <h3>3. AI Probability</h3>
        <p>
            This is the AI’s confidence level. The bot will only trade when the probability
            meets or exceeds this value.
            Example: 0.70 = 70% confidence required.
        </p>

        <h3>4. Mode (Conservative / Balanced / Aggressive)</h3>
        <p>
            Conservative: fewer trades, higher accuracy.<br>
            Balanced: mix of frequency and safety.<br>
            Aggressive: more trades, higher risk.
        </p>

        <h3>5. How the Strategy Works</h3>
        <p>
            The bot combines indicators, price movement, and AI analysis. A trade is only executed
            when ALL conditions meet your thresholds.
        </p>

        <h3>6. When to Adjust</h3>
        <p>
            If the bot is not trading → lower thresholds slightly.<br>
            If the bot is trading too often → increase thresholds.
        </p>

        <h3>Best Practice</h3>
        <p>
            Always test strategies in Paper mode first before using Live mode.
        </p>

        </div>
    </div>

    <div id="scalperInfoModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:9999;justify-content:center;align-items:center;">

    <div style="background:#111827;padding:25px;border-radius:12px;max-width:720px;color:white;max-height:85vh;overflow-y:auto;">

        <button onclick="closeScalperInfo()" style="float:right;">X</button>

        <h2>How to Use Elite Rapid Scalper</h2>

        <h3>What it does</h3>
        <p>Elite Rapid Scalper is designed for short-term trade setups. It helps users preview fast scalp opportunities using symbol, trade side, amount, target, and mode settings.</p>


        <h3>How the logic works</h3>
        <p>The tool takes your selected market, direction, dollar amount, target percentage, and scalp mode. It then builds a controlled scalp setup and estimates the trade outcome before or during paper testing.</p>


        <h3>Symbol</h3>
        <p>Choose the market you want to test, such as BTC/USD, ETH/USD, XRP/USD, SOL/USD, ADA/USD, or DOGE/USD. Higher-volume pairs usually produce cleaner test results.</p>


        <h3>Side</h3>
        <p>Choose Buy if you expect the price to rise. Choose Sell if you expect the price to fall. The selected side controls the direction of the scalp setup.</p>


        <h3>Amount USD</h3>
        <p>This is the simulated dollar amount used for the scalp. Start small during testing. Larger amounts increase exposure and can increase both gains and losses.</p>


        <h3>Target</h3>
        <p>The target is the profit move the setup is aiming for. A 0.5% target is tighter and may trigger more often. A 1.0% target requires a stronger move but may produce a larger result.</p>


        <h3>Mode</h3>
        <p>Conservative looks for safer conditions. Momentum focuses on directional strength. Bounce is used when price may be recovering after a move down or reacting from a support area.</p>


        <h3>Create Rapid Scalper Preview</h3>
        <p>This creates a preview only. No live trade is placed. Use this first to review the setup before running a paper trade.</p>


        <h3>Run Paper Trade</h3>
        <p>This runs the setup in paper mode. It allows users to test the scalp logic with simulated funds before using any real trading environment.</p>


        <h3>How to set it up properly</h3>
        <p>Start with BTC/USD or ETH/USD, use Buy or Sell based on the current market direction, keep the amount small, choose a 0.5% target first, and use Conservative or Momentum mode while testing.</p>


        <h3>Best practice</h3>
        <p>Use preview first, then paper trade. Review the result in Recent Rapid Scalper Setups. Do not use Live mode until the setup has been tested repeatedly and behaves as expected.</p>


        <h3>Important</h3>
        <p>Rapid scalping is higher risk because short-term price movement can change quickly. This tool does not guarantee profit. It follows the selected setup and market conditions.</p>

    </div>
</div>

    <script src="/static/lightweight-charts.js"></script>
    <script src="/static/app.js"></script>
    <div id="chartFullscreenModal" class="chart-fullscreen-modal">
        <div class="chart-fullscreen-shell">
            <div class="chart-fullscreen-header">
                <span id="chartFullscreenTitle">Fullscreen Chart</span>
                <button type="button" id="closeChartFullscreen" class="chart-fullscreen-close">Close</button>
            </div>

            <div id="chartFullscreenMount" class="chart-fullscreen-mount"></div>
        </div>
    </div>

    </body>
    </html>
    """


app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")

