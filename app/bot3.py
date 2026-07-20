import traceback
import ccxt
import pandas as pd
import numpy as np
import time
import logging
from logging.handlers import RotatingFileHandler
import json
import os
import random
import requests
import sqlite3
import itertools
import math
import threading
from statistics import NormalDist
from concurrent.futures import ThreadPoolExecutor, as_completed
def setup_database():
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()

    # Users table (if not already created elsewhere)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            api_key TEXT NOT NULL,
            api_secret TEXT NOT NULL,
            risk REAL DEFAULT 0.01
        )
    """)

    # Symbols per user
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            symbol TEXT NOT NULL,
            is_enabled INTEGER DEFAULT 1,
            UNIQUE(username, symbol)
        )
    """)

    conn.commit()
    conn.close()

def get_user_symbols(username):
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()

    cur.execute(
        "SELECT symbol FROM user_symbols WHERE username = ? AND is_enabled = 1",
        (username,)
    )

    rows = cur.fetchall()
    conn.close()

    return [row[0] for row in rows]

def add_user_symbol(username, symbol):
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO user_symbols (username, symbol, is_enabled) VALUES (?, ?, 1)",
        (username, symbol)
    )

    conn.commit()
    conn.close()


from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import balanced_accuracy_score, brier_score_loss, roc_auc_score
from datetime import datetime, timezone
try:
    from db import get_users, init_db
    LEGACY_RUNTIME_AVAILABLE = True
except ImportError:
    # The Nexora backend owns users and exchange keys. Its paper engine only
    # needs public Kraken data, so legacy standalone database hooks are optional.
    get_users = lambda: []
    init_db = lambda: None
    LEGACY_RUNTIME_AVAILABLE = False

BOT_DATA_DIR = os.path.abspath(
    os.environ.get("NEXORA_BOT_DATA_DIR", os.path.dirname(__file__))
)
os.makedirs(BOT_DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        RotatingFileHandler(
            os.path.join(BOT_DATA_DIR, "bot.log"),
            maxBytes=500_000,
            backupCount=3
        ),
        logging.StreamHandler()
    ]
)

# ===== Constant settings =====
SYMBOLS = ['BTC/USD', 'ETH/USD', 'XRP/USD', 'SOL/USD']
TIMEFRAME = '15m'
HIGHER_TIMEFRAME = '1h'
LOWER_TIMEFRAME = '5m'
DASHBOARD_FILE = os.path.join(BOT_DATA_DIR, "dashboard_status.json")
BASE_RISK = 0.01
STOP_LOSS = 0.98
TAKE_PROFIT = 1.05
COOLDOWN_SECONDS = 7200
PARTIAL_TAKE_PROFIT = 1.02
PARTIAL_SELL_PERCENT = 0.50
TRAIL_START = 1.03
TRAIL_DISTANCE = 0.015
AI_THRESHOLD = 0.40
BASE_SCORE_THRESHOLD = 55
MIN_AI_THRESHOLD = 0.35
MAX_AI_THRESHOLD = 0.70
LOSS_STREAK_PAUSE_LIMIT = 3
CONTROL_FILE = os.path.join(BOT_DATA_DIR, "bot_control.json")
TRADE_RESULTS_FILE = os.path.join(BOT_DATA_DIR, "trade_results.csv")
MARKET_MEMORY_FILE = os.path.join(BOT_DATA_DIR, "market_memory.csv")
FEATURE_REGIME_MEMORY_FILE = os.path.join(BOT_DATA_DIR, "feature_regime_memory.csv")
FORECAST_MEMORY_FILE = os.path.join(BOT_DATA_DIR, "forecast_memory.csv")
GLOBAL_MARKET_MEMORY_FILE = os.path.join(BOT_DATA_DIR, "global_market_memory.csv")
EXECUTION_JOURNAL_FILE = os.path.join(BOT_DATA_DIR, "execution_journal.csv")
FEATURES = [
    "rsi",
    "macd",
    "macd_signal",
    "ema50",
    "ema200",
    "return_1",
    "return_3",
    "return_5",
    "volatility",
    "volume_ratio",
    "ema_distance",
    "trend_strength",

    "atr",
    "atr_percent",

    "bb_upper_distance",
    "bb_lower_distance",
    "bb_width",

    "momentum_3",
    "momentum_5",

    "volume_acceleration",

    "candle_body_strength",
    "upper_wick_ratio",
    "lower_wick_ratio",

    "distance_from_high_20",
    "distance_from_low_20",

    "ema_slope",
    "price_acceleration",

    "higher_highs_20",
    "higher_lows_20",
    "lower_highs_20",
    "lower_lows_20",

    "range_position_20",
    "breakout_pressure_20",
    "breakdown_pressure_20",

    "resistance_distance_20",
    "support_distance_20"
  ]
PRIORITY_TRADE_SYMBOLS = [
    "XLM/USD",
    "XLM/USDT",
  ]

PAPER_MODE = True  # This reviewed build is intentionally simulation-only.
PAPER_BALANCE_USD = 1000
PAPER_START_BALANCE = 1000
PAPER_STATE_FILE = os.path.join(BOT_DATA_DIR, "paper_state.json")
PAPER_TRADES_FILE = os.path.join(BOT_DATA_DIR, "paper_trades.csv")
MODEL_CACHE = {}
MODEL_CACHE_TTL = 900
MODEL_ROLLBACK_CACHE = {}
KRAKEN_DISCOVERY_CACHE_FILE = os.path.join(BOT_DATA_DIR, "kraken_tradeable_symbols.json")
KRAKEN_DISCOVERY_CACHE_TTL = 21600
TRAINING_SKIP_CACHE = {}
TRAINING_SKIP_TTL = 300
LIVE_TRADING_CONFIRMATION = "NO"
TRIPLE_BARRIER_HORIZON = 12
TRIPLE_BARRIER_PROFIT_ATR = 2.0
TRIPLE_BARRIER_STOP_ATR = 1.5
TRIPLE_BARRIER_MIN_PROFIT = 0.008
TRIPLE_BARRIER_MIN_STOP = 0.006
KRAKEN_FEE_BPS_PER_SIDE = 26.0
DEFAULT_SPREAD_BPS = 8.0
DEFAULT_SLIPPAGE_BPS_PER_SIDE = 5.0
DEFAULT_LATENCY_BPS = 2.0
MIN_HISTORY_DAYS = max(365, int(os.getenv("NEXORA_MIN_HISTORY_DAYS", "365")))
MAX_HISTORY_DAYS = min(1095, max(MIN_HISTORY_DAYS, int(os.getenv("NEXORA_MAX_HISTORY_DAYS", "1095"))))
HISTORY_DIR = os.path.join(BOT_DATA_DIR, "point_in_time_history")
EXPERIMENT_REGISTRY_FILE = os.path.join(BOT_DATA_DIR, "model_experiments.jsonl")
MODEL_REGISTRY_FILE = os.path.join(BOT_DATA_DIR, "model_registry.json")
DRIFT_MONITOR_FILE = os.path.join(BOT_DATA_DIR, "drift_monitor.json")
EXTERNAL_FEATURE_DIR = os.path.join(BOT_DATA_DIR, "external_features")
MIN_TRAINING_ROWS = 500
MAX_CALIBRATION_ECE = 0.08
MAX_MODEL_DISAGREEMENT = 0.25
MAX_FEATURE_DRIFT_Z = 5.0
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(EXTERNAL_FEATURE_DIR, exist_ok=True)
MIN_TRADE_USD = 100
PLAN_POSITION_LIMITS = {
    "basic": 2,
    "pro": 5,
    "elite": 15
}

DEFAULT_PLAN = "basic"
MIN_ROTATION_RANK = 78
MIN_ROTATION_EDGE = 7
MAX_SAME_SECTOR_POSITIONS = 2
MAX_CORRELATION_RISK = 0.85
MAX_NEGATIVE_GOVERNANCE_IMPACT = -15
MAX_THRESHOLD_RELIEF = 8
MAX_AI_THRESHOLD_RELIEF = 0.05
FORECAST_CONFIDENCE_THRESHOLD = 0.65
BREAKOUT_FORECAST_THRESHOLD = 0.70
PANIC_FORECAST_THRESHOLD = 0.80
MIN_SECTOR_ROTATION_RANK = 55
MACRO_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"]
MACRO_MIN_SYMBOLS = 2
KRAKEN_ALLOWED_QUOTES = ["USD", "USDT"]
KRAKEN_MIN_CANDLE_COUNT = 120
KRAKEN_MIN_QUOTE_VOLUME_USD = 50000
KRAKEN_MAX_SPREAD_PERCENT = 0.015
KRAKEN_EXCLUDED_SYMBOL_KEYWORDS = [
    ".d",
    ".f",
    "PERP",
    "FUT",
    "MARGIN",
    "UP/",
    "DOWN/"
]

TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

STATE_FILE = os.path.join(BOT_DATA_DIR, "state.json")
TRADES_FILE = os.path.join(BOT_DATA_DIR, "trades.csv")
STRATEGY_FILE = os.path.join(BOT_DATA_DIR, "best_strategy.json")

def get_user_plan(username):
    if username == "marty":
        return "elite"

    return DEFAULT_PLAN


def get_user_max_open_positions(username):
    plan = get_user_plan(username).lower()

    return PLAN_POSITION_LIMITS.get(
        plan,
        PLAN_POSITION_LIMITS[DEFAULT_PLAN]
    )

# ===== INIT =====
if LEGACY_RUNTIME_AVAILABLE:
    init_db()

    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w") as f:
            json.dump({"positions": {}}, f)

    if not os.path.exists(TRADES_FILE):
        pd.DataFrame(columns=[
            "time", "username", "symbol", "entry", "exit", "amount", "pnl", "result"
        ]).to_csv(TRADES_FILE, index=False)

# ===== UTIL =====
def is_kraken_market_eligible(exchange, symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)

        bid = ticker.get("bid")
        ask = ticker.get("ask")
        quote_volume = ticker.get("quoteVolume")

        if bid is None or ask is None:
            print(f"{symbol}: rejected, missing bid/ask")
            return False

        bid = float(bid)
        ask = float(ask)

        if bid <= 0 or ask <= 0:
            print(f"{symbol}: rejected, invalid bid/ask")
            return False

        spread_percent = (ask - bid) / ask

        if spread_percent > KRAKEN_MAX_SPREAD_PERCENT:
            print(
                f"{symbol}: rejected, spread too wide "
                f"{spread_percent:.4f}"
            )
            return False

        if quote_volume is not None:
            quote_volume = float(quote_volume)

            if quote_volume < KRAKEN_MIN_QUOTE_VOLUME_USD:
                print(
                    f"{symbol}: rejected, quote volume too low "
                    f"{quote_volume:.2f}"
                )
                return False

        raw_df = fetch(exchange, symbol, limit=KRAKEN_MIN_CANDLE_COUNT)

        if raw_df is None or raw_df.empty:
            print(f"{symbol}: rejected, no candle data")
            return False

        if len(raw_df) < KRAKEN_MIN_CANDLE_COUNT:
            print(
                f"{symbol}: rejected, insufficient candles "
                f"{len(raw_df)}"
            )
            return False

        if raw_df["close"].isnull().any():
            print(f"{symbol}: rejected, invalid candle close data")
            return False

        return True

    except Exception as e:
        print(f"{symbol}: rejected, eligibility error {repr(e)}")
        return False


def discover_kraken_tradeable_symbols(exchange):
    try:
        if os.path.exists(KRAKEN_DISCOVERY_CACHE_FILE):
            cache_age = (
                time.time()
                - os.path.getmtime(KRAKEN_DISCOVERY_CACHE_FILE)
            )

            if cache_age < KRAKEN_DISCOVERY_CACHE_TTL:
                with open(
                    KRAKEN_DISCOVERY_CACHE_FILE,
                    "r"
                ) as f:
                    cached_symbols = json.load(f)

                print(
                    f"KRAKEN DISCOVERY CACHE: "
                    f"loaded {len(cached_symbols)} symbols"
                )

                return cached_symbols

        markets = exchange.load_markets()

    except Exception as e:
        print(f"KRAKEN DISCOVERY ERROR: {repr(e)}")
        return []

    eligible_symbols = []

    for symbol, market in markets.items():
        try:
            if not market.get("active", False):
                continue

            if market.get("spot") is not True:
                continue

            base = market.get("base")
            quote = market.get("quote")

            if not base or not quote:
                continue

            if quote not in KRAKEN_ALLOWED_QUOTES:
                continue

            blocked = False

            for keyword in KRAKEN_EXCLUDED_SYMBOL_KEYWORDS:
                if keyword in symbol.upper():
                    blocked = True
                    break

            if blocked:
                continue

            if "/" not in symbol:
                continue

            if not is_kraken_market_eligible(exchange, symbol):
                continue

            eligible_symbols.append(symbol)

        except Exception:
            continue

    eligible_symbols = sorted(set(eligible_symbols))

    try:
        with open(
            KRAKEN_DISCOVERY_CACHE_FILE,
            "w"
        ) as f:
            json.dump(eligible_symbols, f)

    except Exception as cache_error:
        print(
            f"KRAKEN DISCOVERY CACHE WRITE ERROR: "
            f"{repr(cache_error)}"
        )

    print(
        f"KRAKEN DISCOVERY: found {len(eligible_symbols)} eligible spot symbols"
    )

    return eligible_symbols

def get_user_tradeable_symbols(username, exchange):
    cached_symbols = []

    if os.path.exists(KRAKEN_DISCOVERY_CACHE_FILE):
        try:
            with open(KRAKEN_DISCOVERY_CACHE_FILE, "r") as f:
                cached_symbols = json.load(f)

            print(
                f"KRAKEN DISCOVERY CACHE: "
                f"using cached universe with {len(cached_symbols)} symbols"
            )

        except Exception as cache_error:
            print(
                f"KRAKEN DISCOVERY CACHE READ ERROR: "
                f"{repr(cache_error)}"
            )

    if cached_symbols:
        discovered_symbols = cached_symbols
    else:
        discovered_symbols = discover_kraken_tradeable_symbols(exchange)

    if not discovered_symbols:
        print(
            f"{username}: Kraken discovery returned no eligible symbols"
        )
        return []

    max_active_symbols = 60

    priority_symbols = [
        symbol for symbol in PRIORITY_TRADE_SYMBOLS
        if symbol in discovered_symbols
    ]

    remaining_symbols = [
        symbol for symbol in discovered_symbols
        if symbol not in priority_symbols
    ]

    approved_symbols = (
        priority_symbols + remaining_symbols
    )[:max_active_symbols]

    print(
        f"{username}: approved Kraken tradeable symbols = "
        f"{len(approved_symbols)} of {len(discovered_symbols)} discovered"
    )

    return approved_symbols


def send_alert(msg):
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception:
        pass

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "positions": {},
            "cash": {},
            "cooldowns": {}
        }

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except Exception:
        return {
            "positions": {},
            "cash": {},
            "cooldowns": {}
        }

    if "positions" not in state:
        state["positions"] = {}

    if "cash" not in state:
        state["cash"] = {}

    if "cooldowns" not in state:
        state["cooldowns"] = {}

    return state


def save_state(state):
    atomic_json_write(STATE_FILE, state)


def atomic_json_write(path, payload):
    """Durably replace JSON without exposing readers to a partial file."""
    temp_file = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, path)
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

def save_dashboard_status(username, cash, position_value, equity, pnl, pct, open_count, positions):
    dashboard_data = {
        "username": username,
        "updated_at": datetime.now().isoformat(),
        "cash": round(cash, 2),
        "position_value": round(position_value, 2),
        "equity": round(equity, 2),
        "pnl": round(pnl, 2),
        "pnl_percent": round(pct, 2),
        "open_positions": open_count,
        "positions": positions.get(username, {})
    }

    atomic_json_write(DASHBOARD_FILE, dashboard_data)

def load_paper_state():
    if not os.path.exists(PAPER_STATE_FILE):
        return {
            "cash": {},
            "positions": {}
        }


    try:
        with open(PAPER_STATE_FILE, "r") as f:
            state = json.load(f)
    except Exception:
        return {
            "cash": {},
            "positions": {}
        }

    if "cash" not in state:
        state["cash"] = {}

    if "positions" not in state:
        state["positions"] = {}

    return state

def save_paper_state(state):
    atomic_json_write(PAPER_STATE_FILE, state)

def log_paper_trade(username, symbol, side, price, amount, trade_value, pnl=0):
    file_exists = os.path.exists(PAPER_TRADES_FILE)

    with open(PAPER_TRADES_FILE, "a") as f:
        if not file_exists:
            f.write("time,username,symbol,side,price,amount,trade_value,pnl\n")

        f.write(
            f"{datetime.now()},{username},{symbol},{side},{price},{amount},{trade_value},{pnl}\n"
        )

def create_exchange(api_key, api_secret):
    return ccxt.kraken({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True
    })

# ===== DATA =====
def fetch(exchange, symbol, limit=300):
    bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=limit)
    df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
    return df
def fetch_multi_timeframe(exchange, symbol):
    main_df = fetch(exchange, symbol)

    higher_bars = exchange.fetch_ohlcv(
        symbol,
        timeframe=HIGHER_TIMEFRAME,
        limit=300
    )

    lower_bars = exchange.fetch_ohlcv(
        symbol,
        timeframe=LOWER_TIMEFRAME,
        limit=300
    )

    higher_df = pd.DataFrame(
        higher_bars,
        columns=['time', 'open', 'high', 'low', 'close', 'volume']
    )

    lower_df = pd.DataFrame(
        lower_bars,
        columns=['time', 'open', 'high', 'low', 'close', 'volume']
    )

    return {
        "main": main_df,
        "higher": higher_df,
        "lower": lower_df
    }


def _history_path(symbol):
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    return os.path.join(HISTORY_DIR, f"{safe_symbol}_{TIMEFRAME}.csv.gz")


def fetch_historical_ohlcv(exchange, symbol, days=MIN_HISTORY_DAYS):
    """Fetch chronological point-in-time candles without silently accepting gaps."""
    timeframe_ms = int(exchange.parse_timeframe(TIMEFRAME) * 1000)
    end_ms = int(time.time() * 1000)
    since = end_ms - int(days * 86_400_000)
    rows = []
    previous_last = None

    while since < end_ms:
        batch = exchange.fetch_ohlcv(
            symbol,
            timeframe=TIMEFRAME,
            since=since,
            limit=720,
        )
        if not batch:
            break
        rows.extend(batch)
        last_time = int(batch[-1][0])
        if previous_last is not None and last_time <= previous_last:
            break
        previous_last = last_time
        since = last_time + timeframe_ms
        if len(batch) < 2:
            break

    frame = pd.DataFrame(
        rows,
        columns=["time", "open", "high", "low", "close", "volume"],
    )
    if frame.empty:
        raise ValueError(f"No historical candles returned for {symbol}")
    frame = frame.drop_duplicates("time", keep="last").sort_values("time")
    frame = frame[frame["time"] <= end_ms].reset_index(drop=True)
    return frame


def validate_point_in_time_history(frame, minimum_days=MIN_HISTORY_DAYS):
    required = {"time", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Historical dataset missing columns: {sorted(required - set(frame.columns))}")
    if frame["time"].duplicated().any() or not frame["time"].is_monotonic_increasing:
        raise ValueError("Historical candles must be unique and chronological")
    coverage_days = (float(frame["time"].iloc[-1]) - float(frame["time"].iloc[0])) / 86_400_000
    if coverage_days < minimum_days * 0.95:
        raise ValueError(
            f"Only {coverage_days:.1f} days of history available; "
            f"at least {minimum_days} point-in-time days are required"
        )
    expected_ms = 15 * 60 * 1000
    large_gaps = frame["time"].diff().dropna() > expected_ms * 8
    if large_gaps.mean() > 0.002:
        raise ValueError("Historical dataset contains excessive unexplained gaps")
    return coverage_days


def load_training_history(exchange, symbol):
    path = _history_path(symbol)
    cached = pd.DataFrame()
    if os.path.exists(path):
        try:
            cached = pd.read_csv(path)
            if time.time() - os.path.getmtime(path) < 3600:
                validate_point_in_time_history(cached)
                return cached
        except Exception:
            cached = pd.DataFrame()

    requested_days = min(MAX_HISTORY_DAYS, max(MIN_HISTORY_DAYS, 365))
    fresh = fetch_historical_ohlcv(exchange, symbol, requested_days)
    combined = pd.concat([cached, fresh], ignore_index=True)
    combined = combined.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)
    validate_point_in_time_history(combined)
    combined.to_csv(path, index=False, compression="gzip")
    return combined


def load_external_feature_snapshot(symbol, as_of_ms):
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    path = os.path.join(EXTERNAL_FEATURE_DIR, f"{safe_symbol}.json")
    required_by_policy = os.getenv("NEXORA_REQUIRE_EXTERNAL_FEATURES", "NO") == "YES"
    if not os.path.exists(path):
        return {"available": False, "required": required_by_policy, "reason": "no external snapshot"}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
        required = {
            "as_of_ms", "event_time_ms", "source_quality", "relevance",
            "novelty", "sentiment", "confirmed_status",
        }
        missing = required - set(snapshot)
        if missing:
            raise ValueError(f"missing fields {sorted(missing)}")
        if float(snapshot["as_of_ms"]) > float(as_of_ms):
            raise ValueError("snapshot contains future information")
        if float(snapshot["event_time_ms"]) > float(snapshot["as_of_ms"]):
            raise ValueError("event occurs after snapshot publication time")
        if float(as_of_ms) - float(snapshot["as_of_ms"]) > 60 * 60 * 1000:
            raise ValueError("external snapshot is stale")
        return {"available": True, "required": required_by_policy, **snapshot}
    except Exception as error:
        return {
            "available": False,
            "required": required_by_policy,
            "reason": f"{type(error).__name__}: {error}",
        }


def execution_cost_rate(
    fee_bps_per_side=KRAKEN_FEE_BPS_PER_SIDE,
    spread_bps=DEFAULT_SPREAD_BPS,
    slippage_bps_per_side=DEFAULT_SLIPPAGE_BPS_PER_SIDE,
    latency_bps=DEFAULT_LATENCY_BPS,
):
    total_bps = (
        2 * float(fee_bps_per_side)
        + float(spread_bps)
        + 2 * float(slippage_bps_per_side)
        + float(latency_bps)
    )
    return total_bps / 10_000.0


def apply_triple_barrier_labels(df, horizon=TRIPLE_BARRIER_HORIZON):
    """Label by the first volatility-adjusted barrier touched, conservatively."""
    labelled = df.copy()
    targets = np.full(len(labelled), np.nan)
    returns = np.full(len(labelled), np.nan)
    end_times = np.full(len(labelled), np.nan)
    events = np.full(len(labelled), None, dtype=object)
    profit_barriers = np.full(len(labelled), np.nan)
    stop_barriers = np.full(len(labelled), np.nan)
    cost_rate = execution_cost_rate()

    for position in range(len(labelled)):
        if position + horizon >= len(labelled):
            continue
        entry = float(labelled["close"].iloc[position])
        volatility = float(labelled["atr_percent"].iloc[position])
        if not np.isfinite(entry) or entry <= 0 or not np.isfinite(volatility) or volatility <= 0:
            continue

        profit_distance = max(TRIPLE_BARRIER_MIN_PROFIT, volatility * TRIPLE_BARRIER_PROFIT_ATR)
        stop_distance = max(TRIPLE_BARRIER_MIN_STOP, volatility * TRIPLE_BARRIER_STOP_ATR)
        upper = entry * (1 + profit_distance)
        lower = entry * (1 - stop_distance)
        profit_barriers[position] = profit_distance
        stop_barriers[position] = stop_distance
        event = "time"
        exit_price = float(labelled["close"].iloc[position + horizon])
        end_position = position + horizon

        for future_position in range(position + 1, position + horizon + 1):
            high = float(labelled["high"].iloc[future_position])
            low = float(labelled["low"].iloc[future_position])
            hit_profit = high >= upper
            hit_stop = low <= lower
            if hit_profit and hit_stop:
                # OHLC cannot reveal intrabar ordering. Assume the adverse fill.
                event, exit_price, end_position = "stop_ambiguous", lower, future_position
                break
            if hit_stop:
                event, exit_price, end_position = "stop", lower, future_position
                break
            if hit_profit:
                event, exit_price, end_position = "profit", upper, future_position
                break

        net_return = (exit_price / entry) - 1.0 - cost_rate
        targets[position] = 1.0 if event == "profit" and net_return > 0 else 0.0
        returns[position] = net_return
        end_times[position] = float(labelled["time"].iloc[end_position])
        events[position] = event

    labelled["target"] = targets
    labelled["target_return"] = returns
    labelled["label_end_time"] = end_times
    labelled["barrier_event"] = events
    labelled["profit_barrier"] = profit_barriers
    labelled["stop_barrier"] = stop_barriers
    return labelled


def indicators(df):
    df = df.copy()

    df['rsi'] = RSIIndicator(df['close'], window=14).rsi()

    macd = MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    df['ema50'] = EMAIndicator(df['close'], window=50).ema_indicator()
    df['ema200'] = EMAIndicator(df['close'], window=200).ema_indicator()
    df["return_1"] = df["close"].pct_change(1)
    df["return_3"] = df["close"].pct_change(3)
    df["return_5"] = df["close"].pct_change(5)

    df["volatility"] = df["close"].pct_change().rolling(20).std()

    df["volume_ma20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma20"]

    df["ema_distance"] = (df["close"] - df["ema50"]) / df["ema50"]
    df["trend_strength"] = (df["ema50"] - df["ema200"]) / df["ema200"]
    atr = AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14
    )

    df["atr"] = atr.average_true_range()
    df["atr_percent"] = df["atr"] / df["close"]

    bb = BollingerBands(close=df["close"], window=20, window_dev=2)

    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_middle"] = bb.bollinger_mavg()

    df["bb_upper_distance"] = (
        (df["bb_upper"] - df["close"]) / df["close"]
    )

    df["bb_lower_distance"] = (
        (df["close"] - df["bb_lower"]) / df["close"]
    )

    df["bb_width"] = (
        (df["bb_upper"] - df["bb_lower"]) / df["close"]
    )

    df["momentum_3"] = df["close"].pct_change(3)
    df["momentum_5"] = df["close"].pct_change(5)

    df["volume_acceleration"] = (
        df["volume_ratio"].pct_change()
    )

    candle_range = (df["high"] - df["low"]).replace(0, np.nan)

    df["candle_body_strength"] = (
        abs(df["close"] - df["open"]) / candle_range
    )

    df["upper_wick_ratio"] = (
        (df["high"] - df[["open", "close"]].max(axis=1)) / candle_range
    )

    df["lower_wick_ratio"] = (
        (df[["open", "close"]].min(axis=1) - df["low"]) / candle_range
    )

    rolling_high_20 = df["high"].rolling(20).max()
    rolling_low_20 = df["low"].rolling(20).min()

    df["distance_from_high_20"] = (
        (rolling_high_20 - df["close"]) / df["close"]
    )

    df["distance_from_low_20"] = (
        (df["close"] - rolling_low_20) / df["close"]
    )

    df["ema_slope"] = df["ema50"].pct_change(5)

    df["price_acceleration"] = (
        df["return_1"] - df["return_3"]
    )

    rolling_high_20 = df["high"].rolling(20).max()
    rolling_low_20 = df["low"].rolling(20).min()

    previous_high_20 = rolling_high_20.shift(5)
    previous_low_20 = rolling_low_20.shift(5)

    df["higher_highs_20"] = (
        rolling_high_20 > previous_high_20
    ).astype(int)

    df["higher_lows_20"] = (
        rolling_low_20 > previous_low_20
    ).astype(int)

    df["lower_highs_20"] = (
        rolling_high_20 < previous_high_20
    ).astype(int)

    df["lower_lows_20"] = (
        rolling_low_20 < previous_low_20
    ).astype(int)

    range_20 = (rolling_high_20 - rolling_low_20).replace(0, np.nan)

    df["range_position_20"] = (
        (df["close"] - rolling_low_20) / range_20
    )

    df["breakout_pressure_20"] = (
        (df["close"] - previous_high_20) / df["close"]
    )

    df["breakdown_pressure_20"] = (
        (previous_low_20 - df["close"]) / df["close"]
    )

    df["resistance_distance_20"] = (
        (rolling_high_20 - df["close"]) / df["close"]
    )

    df["support_distance_20"] = (
        (df["close"] - rolling_low_20) / df["close"]
    )

    df.replace([np.inf, -np.inf], np.nan, inplace=True)

    for feature in FEATURES:
         if feature not in df.columns:
             df[feature] = np.nan

    df[FEATURES] = df[FEATURES].apply(pd.to_numeric, errors="coerce")

    df[FEATURES] = df[FEATURES].clip(
        lower=-10,
        upper=10
    )

    df = apply_triple_barrier_labels(df)
    df = df.iloc[200:].copy()
    # Keep the newest feature-complete rows for inference even though their
    # forward-looking labels are not observable yet.
    df.dropna(subset=FEATURES, inplace=True)

    return df

# ===== AI =====
def _train_ai_single_split_legacy(df):
    df = df.dropna(subset=FEATURES + ["target"]).copy()


    if len(df) < 60:
        print(
            f"AI skipped: not enough usable rows after indicators | rows={len(df)}"
        )
        return None

    X = df[FEATURES]
    y = df["target"]
    print("AI target counts:", y.value_counts().to_dict())

    if len(y.unique()) < 2:
        print("AI skipped: only one class found.")
        return None

    if y.value_counts().min() < 3:
        print("AI skipped: not enough balanced examples.")
        return None
    split_at = int(len(df) * 0.80)
    if split_at < 40 or len(df) - split_at < 12:
        print("AI skipped: insufficient chronological validation window.")
        return None

    X_train, X_validation = X.iloc[:split_at], X.iloc[split_at:]
    y_train, y_validation = y.iloc[:split_at], y.iloc[split_at:]

    if len(y_train.unique()) < 2 or len(y_validation.unique()) < 2:
        print("AI skipped: chronological validation contains only one class.")
        return None

    model = RandomForestClassifier(
        n_estimators=500,
        max_depth=12,
        min_samples_leaf=2,
        min_samples_split=4,
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=1
    )

    model.fit(X_train, y_train)

    validation_prob = model.predict_proba(X_validation)[:, 1]
    validation_pred = (validation_prob >= 0.50).astype(int)
    validation_auc = roc_auc_score(y_validation, validation_prob)
    validation_balanced_accuracy = balanced_accuracy_score(
        y_validation,
        validation_pred
    )
    print(
        "AI chronological validation | "
        f"auc={validation_auc:.3f} | "
        f"balanced_accuracy={validation_balanced_accuracy:.3f}"
    )

    if validation_auc < 0.52 or validation_balanced_accuracy < 0.50:
        print("AI skipped: model failed minimum out-of-sample quality gates.")
        return None

    # Refit only after the chronological quality gate has passed.
    model.fit(X, y)

    return model


def expected_calibration_error(y_true, probabilities, bins=10):
    y_true = np.asarray(y_true, dtype=float)
    probabilities = np.asarray(probabilities, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    error = 0.0
    for lower, upper in zip(edges[:-1], edges[1:]):
        if upper == 1.0:
            mask = (probabilities >= lower) & (probabilities <= upper)
        else:
            mask = (probabilities >= lower) & (probabilities < upper)
        if not mask.any():
            continue
        error += mask.mean() * abs(y_true[mask].mean() - probabilities[mask].mean())
    return float(error)


def purged_combinatorial_splits(
    size,
    groups=5,
    test_groups=2,
    purge=TRIPLE_BARRIER_HORIZON,
    embargo=TRIPLE_BARRIER_HORIZON,
):
    if size < groups * 20:
        return []
    all_indices = np.arange(size)
    folds = [np.asarray(part, dtype=int) for part in np.array_split(all_indices, groups)]
    splits = []
    for selected in itertools.combinations(range(groups), test_groups):
        test_index = np.concatenate([folds[index] for index in selected])
        blocked = np.zeros(size, dtype=bool)
        for index in selected:
            start, end = int(folds[index][0]), int(folds[index][-1])
            blocked[max(0, start - purge):min(size, end + embargo + 1)] = True
        train_index = all_indices[~blocked]
        if len(train_index) and len(test_index):
            splits.append((train_index, np.sort(test_index)))
    return splits


def bootstrap_auc_lower_bound(y_true, probabilities, iterations=150, confidence=0.95):
    y_true = np.asarray(y_true, dtype=int)
    probabilities = np.asarray(probabilities, dtype=float)
    rng = np.random.default_rng(42)
    scores = []
    for _ in range(iterations):
        sample = rng.integers(0, len(y_true), len(y_true))
        if len(np.unique(y_true[sample])) < 2:
            continue
        scores.append(roc_auc_score(y_true[sample], probabilities[sample]))
    if not scores:
        return 0.0
    return float(np.quantile(scores, (1.0 - confidence) / 2.0))


def classify_feature_regime(frame):
    trend = frame["trend_strength"].to_numpy(dtype=float)
    atr = frame["atr_percent"].to_numpy(dtype=float)
    breakout = frame["breakout_pressure_20"].to_numpy(dtype=float)
    momentum = frame["momentum_5"].to_numpy(dtype=float)
    regimes = np.full(len(frame), "mean_reversion", dtype=object)
    regimes[atr >= 0.025] = "high_volatility"
    regimes[(trend > 0.01) & (momentum > 0)] = "trend"
    regimes[(breakout > 0) & (frame["volume_ratio"].to_numpy(dtype=float) > 1.2)] = "breakout"
    return regimes


def deflated_sharpe_probability(returns, attempted_models=1):
    values = np.asarray(returns, dtype=float)
    if len(values) < 20 or float(np.std(values, ddof=1)) <= 0:
        return 0.0
    sharpe = float(np.mean(values) / np.std(values, ddof=1) * math.sqrt(len(values)))
    trials = max(1, int(attempted_models))
    if trials == 1:
        expected_maximum = 0.0
    else:
        expected_maximum = NormalDist().inv_cdf(1.0 - 1.0 / trials)
    centered = values - values.mean()
    standard = values.std(ddof=1)
    skew = float(np.mean((centered / standard) ** 3))
    kurtosis = float(np.mean((centered / standard) ** 4))
    denominator = math.sqrt(
        max(1e-9, 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe ** 2)
    )
    statistic = (sharpe - expected_maximum) * math.sqrt(max(1, len(values) - 1)) / denominator
    return float(NormalDist().cdf(statistic))


def simulate_execution_outcomes(frame, probabilities, threshold=0.50, max_positions=5):
    probabilities = np.asarray(probabilities, dtype=float)
    selected = np.flatnonzero(probabilities >= threshold)
    open_until = []
    realized = []
    rejected_overlap = 0
    for index in selected:
        timestamp = float(frame["time"].iloc[index])
        open_until = [end for end in open_until if end > timestamp]
        if len(open_until) >= max_positions:
            rejected_overlap += 1
            continue
        net_return = float(frame["target_return"].iloc[index])
        dollar_volume = float(frame["close"].iloc[index] * frame["volume"].iloc[index])
        fill_ratio = max(0.10, min(1.0, dollar_volume * 0.001 / max(MIN_TRADE_USD, 1)))
        realized.append(net_return * fill_ratio)
        open_until.append(float(frame["label_end_time"].iloc[index]))
    attempted_models = 1
    if os.path.exists(EXPERIMENT_REGISTRY_FILE):
        try:
            with open(EXPERIMENT_REGISTRY_FILE, "r", encoding="utf-8") as handle:
                attempted_models = max(1, sum(1 for line in handle if line.strip()) + 1)
        except Exception:
            attempted_models = 1
    return {
        "trade_count": len(realized),
        "mean_net_return": float(np.mean(realized)) if realized else -1.0,
        "median_net_return": float(np.median(realized)) if realized else -1.0,
        "total_net_return": float(np.sum(realized)) if realized else -1.0,
        "rejected_position_overlap": rejected_overlap,
        "attempted_models": attempted_models,
        "deflated_sharpe_probability": deflated_sharpe_probability(realized, attempted_models),
    }


class RegimeCalibratedEnsemble:
    def __init__(self, global_model, specialists, calibrator, metrics, training_frame):
        self.global_model = global_model
        self.specialists = specialists
        self.calibrator = calibrator
        self.validation_metrics = metrics
        self.feature_importances_ = global_model.feature_importances_
        self.feature_mean_ = training_frame[FEATURES].mean().to_numpy(dtype=float)
        self.feature_std_ = training_frame[FEATURES].std().replace(0, 1).to_numpy(dtype=float)

    def _raw_matrix(self, frame):
        matrix = [self.global_model.predict_proba(frame[FEATURES])[:, 1]]
        for model in self.specialists.values():
            matrix.append(model.predict_proba(frame[FEATURES])[:, 1])
        return np.vstack(matrix)

    def predict_proba(self, frame):
        regimes = classify_feature_regime(frame)
        raw = self.global_model.predict_proba(frame[FEATURES])[:, 1]
        for regime_name, model in self.specialists.items():
            mask = regimes == regime_name
            if mask.any():
                raw[mask] = model.predict_proba(frame.loc[mask, FEATURES])[:, 1]
        calibrated = np.clip(self.calibrator.transform(raw), 0.001, 0.999)
        return np.column_stack([1.0 - calibrated, calibrated])

    def disagreement(self, frame):
        return float(np.mean(np.std(self._raw_matrix(frame), axis=0)))

    def drift_z(self, frame):
        current = frame[FEATURES].mean().to_numpy(dtype=float)
        return float(np.nanmax(np.abs((current - self.feature_mean_) / self.feature_std_)))


def _new_validation_model(seed):
    return RandomForestClassifier(
        n_estimators=160,
        max_depth=12,
        min_samples_leaf=4,
        min_samples_split=8,
        max_features="sqrt",
        class_weight="balanced_subsample",
        random_state=seed,
        n_jobs=1,
    )


def record_model_experiment(metrics):
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **metrics}
    with open(EXPERIMENT_REGISTRY_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, allow_nan=False) + "\n")


def train_ai(df):
    labelled = df.dropna(
        subset=FEATURES + ["target", "target_return", "label_end_time"]
    ).copy().reset_index(drop=True)
    if len(labelled) < MIN_TRAINING_ROWS:
        print(f"AI skipped: {len(labelled)} labelled rows; {MIN_TRAINING_ROWS} required.")
        return None
    X, y = labelled[FEATURES], labelled["target"].astype(int)
    if len(y.unique()) < 2 or y.value_counts().min() < 50:
        print("AI skipped: inadequate examples for both target classes.")
        return None

    splits = purged_combinatorial_splits(len(labelled))
    prediction_sum = np.zeros(len(labelled), dtype=float)
    prediction_count = np.zeros(len(labelled), dtype=int)
    fold_auc = []
    for fold_number, (train_index, test_index) in enumerate(splits):
        fold_model = _new_validation_model(100 + fold_number)
        fold_model.fit(X.iloc[train_index], y.iloc[train_index])
        fold_probability = fold_model.predict_proba(X.iloc[test_index])[:, 1]
        prediction_sum[test_index] += fold_probability
        prediction_count[test_index] += 1
        if len(np.unique(y.iloc[test_index])) == 2:
            fold_auc.append(roc_auc_score(y.iloc[test_index], fold_probability))

    valid = prediction_count > 0
    raw_oof = prediction_sum[valid] / prediction_count[valid]
    valid_indices = np.flatnonzero(valid)
    cut = max(1, int(len(valid_indices) * 0.70))
    calibration_indices = valid_indices[:cut]
    evaluation_indices = valid_indices[cut:]
    if len(evaluation_indices) < 100:
        print("AI skipped: insufficient embargoed calibration evaluation rows.")
        return None

    raw_lookup = np.zeros(len(labelled), dtype=float)
    raw_lookup[valid_indices] = raw_oof
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
    calibrator.fit(raw_lookup[calibration_indices], y.iloc[calibration_indices])
    evaluated_probability = calibrator.transform(raw_lookup[evaluation_indices])
    evaluated_target = y.iloc[evaluation_indices].to_numpy()
    auc = roc_auc_score(evaluated_target, evaluated_probability)
    balanced = balanced_accuracy_score(
        evaluated_target,
        (evaluated_probability >= 0.50).astype(int),
    )
    brier = brier_score_loss(evaluated_target, evaluated_probability)
    ece = expected_calibration_error(evaluated_target, evaluated_probability)
    auc_lower = bootstrap_auc_lower_bound(evaluated_target, evaluated_probability)
    economics = simulate_execution_outcomes(
        labelled.iloc[evaluation_indices].reset_index(drop=True),
        evaluated_probability,
    )
    metrics = {
        "rows": len(labelled),
        "folds": len(splits),
        "auc": float(auc),
        "auc_lower_95": float(auc_lower),
        "balanced_accuracy": float(balanced),
        "brier": float(brier),
        "ece": float(ece),
        "worst_fold_auc": float(min(fold_auc)) if fold_auc else 0.0,
        "fold_failure_rate": float(np.mean(np.asarray(fold_auc) <= 0.50)) if fold_auc else 1.0,
        **economics,
    }
    record_model_experiment(metrics)
    print("AI purged validation | " + " | ".join(f"{key}={value:.4f}" if isinstance(value, float) else f"{key}={value}" for key, value in metrics.items()))

    quality_passed = (
        metrics["auc_lower_95"] > 0.50
        and metrics["worst_fold_auc"] >= 0.48
        and metrics["ece"] <= MAX_CALIBRATION_ECE
        and metrics["trade_count"] >= 30
        and metrics["mean_net_return"] > 0
        and metrics["deflated_sharpe_probability"] >= 0.50
    )
    if not quality_passed:
        print("AI skipped: statistical, calibration, or net-value gate failed.")
        return None

    global_model = RandomForestClassifier(
        n_estimators=500,
        max_depth=14,
        min_samples_leaf=4,
        min_samples_split=8,
        max_features="sqrt",
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=1,
    )
    global_model.fit(X, y)
    regimes = classify_feature_regime(labelled)
    specialists = {}
    for regime_name in ("trend", "mean_reversion", "breakout", "high_volatility"):
        mask = regimes == regime_name
        if mask.sum() < 200 or len(np.unique(y[mask])) < 2:
            continue
        specialist = _new_validation_model(1000 + len(specialists))
        specialist.fit(X.loc[mask], y.loc[mask])
        specialists[regime_name] = specialist
    return RegimeCalibratedEnsemble(global_model, specialists, calibrator, metrics, labelled)

def get_cached_model(symbol, df):
    now = time.time()

    skipped_at = TRAINING_SKIP_CACHE.get(symbol)

    if skipped_at and now - skipped_at < 300:
        print(
            f"{symbol}: AI training retry cooldown active, using fallback"
        )
        return None
    cached = MODEL_CACHE.get(symbol)

    if cached:
        cached_model, created_at = cached

        if cached_model is not None and now - created_at < MODEL_CACHE_TTL:
            return cached_model

    model = train_ai(df)

    if model is not None:
        previous = MODEL_CACHE.get(symbol)
        if previous and previous[0] is not None:
            MODEL_ROLLBACK_CACHE[symbol] = previous

        registry = {}
        if os.path.exists(MODEL_REGISTRY_FILE):
            try:
                with open(MODEL_REGISTRY_FILE, "r", encoding="utf-8") as handle:
                    registry = json.load(handle)
            except Exception:
                registry = {}
        metrics = model.validation_metrics
        quality_score = (
            metrics["auc_lower_95"]
            - metrics["ece"]
            + max(-0.10, min(metrics["mean_net_return"], 0.10))
        )
        previous_score = float(registry.get(symbol, {}).get("quality_score", -1.0))
        if previous and quality_score < previous_score:
            print(f"{symbol}: challenger rejected; champion retained.")
            return previous[0]

        MODEL_CACHE[symbol] = (model, now)
        registry[symbol] = {
            "status": "champion",
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "quality_score": quality_score,
            "metrics": metrics,
            "rollback_available": previous is not None,
        }
        atomic_json_write(MODEL_REGISTRY_FILE, registry)

        if symbol in TRAINING_SKIP_CACHE:
            del TRAINING_SKIP_CACHE[symbol]

        return model

    TRAINING_SKIP_CACHE[symbol] = now

    print(
        f"{symbol}: added to AI training quality quarantine"
    )

    return None

def rollback_champion(symbol):
    """Restore the last in-memory champion after a challenger regression."""
    previous = MODEL_ROLLBACK_CACHE.pop(symbol, None)
    if previous is None:
        return False
    MODEL_CACHE[symbol] = previous
    return True

def record_drift_observation(symbol, disagreement, drift_z, calibration_error):
    """Persist deployment-health observations and quarantine repeated failures."""
    state = {}
    if os.path.exists(DRIFT_MONITOR_FILE):
        try:
            with open(DRIFT_MONITOR_FILE, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except Exception:
            state = {}
    entry = state.get(symbol, {"consecutive_failures": 0, "observations": []})
    unhealthy = bool(
        disagreement > MAX_MODEL_DISAGREEMENT
        or drift_z > MAX_FEATURE_DRIFT_Z
        or calibration_error > MAX_CALIBRATION_ECE
    )
    entry["consecutive_failures"] = (
        int(entry.get("consecutive_failures", 0)) + 1 if unhealthy else 0
    )
    entry["quarantined"] = entry["consecutive_failures"] >= 3
    entry["observations"] = (entry.get("observations", []) + [{
        "at": datetime.now(timezone.utc).isoformat(),
        "disagreement": float(disagreement),
        "feature_drift_z": float(drift_z) if np.isfinite(drift_z) else None,
        "calibration_error": float(calibration_error),
        "unhealthy": unhealthy,
    }])[-200:]
    state[symbol] = entry
    atomic_json_write(DRIFT_MONITOR_FILE, state)
    return bool(entry["quarantined"])

def log_feature_importance(symbol, model):
    if model is None:
        return {}

    try:
        importances = model.feature_importances_

        ranked = sorted(
            zip(FEATURES, importances),
            key=lambda x: x[1],
            reverse=True
        )

        top_features = ranked[:6]

        print(
            f"{symbol}: top AI features | " +
            " | ".join([
                f"{name}={score:.3f}"
                for name, score in top_features
            ])
        )

        return {
            name: float(score)
            for name, score in top_features
        }
    except Exception as e:
        print(f"{symbol}: feature importance error: {e}")
        return {}


def ai_prob(model, df):
    latest = df[FEATURES].iloc[[-1]]
    raw_prob = float(model.predict_proba(latest)[0][1])
    return max(0.01, min(raw_prob, 0.99))

def _heuristic_probability_adjustment_legacy(
    raw_prob,
    df,
    regime,
    macro_context,
    timeframe_alignment
):
    last = df.iloc[-1]

    calibrated_prob = raw_prob

    rsi = float(last.get("rsi", 50))
    momentum_3 = float(last.get("momentum_3", 0))
    momentum_5 = float(last.get("momentum_5", 0))
    trend_strength = float(last.get("trend_strength", 0))
    volume_ratio = float(last.get("volume_ratio", 1))
    range_position = float(last.get("range_position_20", 0.5))
    breakout_pressure = float(last.get("breakout_pressure_20", 0))
    ema_slope = float(last.get("ema_slope", 0))
    price_acceleration = float(last.get("price_acceleration", 0))
    candle_body_strength = float(last.get("candle_body_strength", 0))

    signal_bonus = 0.0

    if 42 <= rsi <= 70:
        signal_bonus += 0.04

    if momentum_3 > 0:
        signal_bonus += 0.04

    if momentum_5 > 0:
        signal_bonus += 0.04

    if trend_strength > 0:
        signal_bonus += 0.05

    if volume_ratio >= 1.0:
        signal_bonus += 0.03

    if range_position >= 0.50:
        signal_bonus += 0.04

    if breakout_pressure > 0:
        signal_bonus += 0.05

    if ema_slope > 0:
        signal_bonus += 0.04

    if price_acceleration > 0:
        signal_bonus += 0.04

    if candle_body_strength >= 0.40:
        signal_bonus += 0.03

    calibrated_prob += min(signal_bonus, 0.28)

    regime_name = regime.get("regime", "unknown")

    if regime_name == "bull_trend":
        calibrated_prob += 0.07

    elif regime_name == "sideways_chop":
        calibrated_prob += 0.00

    elif regime_name == "high_volatility":
        calibrated_prob -= 0.03

    elif regime_name in ["bear_trend", "crash_risk"]:
        calibrated_prob -= 0.20

    macro_regime = macro_context.get("macro_regime", "macro_neutral")

    if macro_regime == "macro_bull_expansion":
        calibrated_prob += 0.08

    elif macro_regime == "macro_altseason_rotation":
        calibrated_prob += 0.10

    elif macro_regime == "macro_accumulation":
        calibrated_prob += 0.05

    elif macro_regime == "macro_volatility_compression":
        calibrated_prob += 0.03

    elif macro_regime == "macro_volatility_expansion":
        calibrated_prob -= 0.04

    elif macro_regime == "macro_distribution":
        calibrated_prob -= 0.10

    elif macro_regime == "macro_bear_cycle":
        calibrated_prob -= 0.15

    elif macro_regime == "macro_panic_event":
        calibrated_prob = 0.01

    alignment = timeframe_alignment.get("direction", "mixed")

    if alignment == "strong_bullish":
        calibrated_prob += 0.08

    elif alignment == "bullish":
        calibrated_prob += 0.05

    elif alignment == "mixed":
        calibrated_prob += 0.00

    if (
        raw_prob >= 0.20
        and regime_name in ["bull_trend", "sideways_chop", "high_volatility"]
        and macro_regime in [
            "macro_bull_expansion",
            "macro_altseason_rotation",
            "macro_accumulation",
            "macro_volatility_compression"
        ]
        and alignment in ["bullish", "strong_bullish"]
        and momentum_3 > 0
        and ema_slope > 0
    ):
        calibrated_prob = max(calibrated_prob, raw_prob + 0.12)

    if (
        regime_name == "sideways_chop"
        and macro_regime == "macro_volatility_compression"
        and alignment == "mixed"
        and momentum_3 > 0
        and price_acceleration > 0
    ):
        calibrated_prob += 0.05

    calibrated_prob = max(0.01, min(calibrated_prob, 0.95))

    return calibrated_prob


def calibrate_ai_probability(
    raw_prob,
    df,
    regime,
    macro_context,
    timeframe_alignment,
):
    """The ensemble probability is already calibrated out-of-fold.

    Regime and macro rules remain separate execution gates and must never be
    added to a probability after calibration.
    """
    return float(np.clip(raw_prob, 0.001, 0.999))


def strategy_score(df):
    last = df.iloc[-1]

    score = 0
    feature_amplification = 0

    rsi = float(last.get("rsi", 50))
    volume_ratio = float(last.get("volume_ratio", 1))
    trend_strength = float(last.get("trend_strength", 0))
    atr_percent = float(last.get("atr_percent", 0))
    range_position = float(last.get("range_position_20", 0.5))
    breakout_pressure = float(last.get("breakout_pressure_20", 0))
    support_distance = float(last.get("support_distance_20", 0))
    resistance_distance = float(last.get("resistance_distance_20", 0))
    candle_body_strength = float(last.get("candle_body_strength", 0))
    lower_wick_ratio = float(last.get("lower_wick_ratio", 0))
    upper_wick_ratio = float(last.get("upper_wick_ratio", 0))
    price_acceleration = float(last.get("price_acceleration", 0))
    ema_slope = float(last.get("ema_slope", 0))
    momentum_3 = float(last.get("momentum_3", 0))
    momentum_5 = float(last.get("momentum_5", 0))

    if last["ema50"] > last["ema200"]:
        score += 15

    if last["close"] > last["ema50"]:
        score += 10

    if trend_strength > 0:
        score += 10

        if trend_strength >= 0.015:
            feature_amplification += 4

    if ema_slope > 0:
        score += 10

        if ema_slope >= 0.010:
            feature_amplification += 4

    if 42 <= rsi <= 68:
        score += 10

        if 48 <= rsi <= 62:
            feature_amplification += 3

    if volume_ratio >= 1.05:
        score += 10

        if volume_ratio >= 1.20:
            feature_amplification += 4

    if price_acceleration > 0:
        score += 10

        if price_acceleration >= 0.015:
            feature_amplification += 4

    if 0.35 <= range_position <= 0.85:
        score += 10

        if 0.45 <= range_position <= 0.75:
            feature_amplification += 3

    if breakout_pressure > -0.003:
        score += 5

        if breakout_pressure > 0:
            feature_amplification += 5

    if support_distance <= 0.03:
        score += 5

        if lower_wick_ratio >= 0.30:
            feature_amplification += 4

    if resistance_distance >= 0.005:
        score += 5

    if candle_body_strength >= 0.45:
        score += 5

        if candle_body_strength >= 0.55:
            feature_amplification += 4

    if lower_wick_ratio > upper_wick_ratio:
        score += 5

    if 0.002 <= atr_percent <= 0.025:
        score += 5

    if momentum_3 > 0:
        feature_amplification += 4

    if momentum_5 > 0:
        feature_amplification += 4

    if (
        momentum_3 > 0
        and momentum_5 > 0
        and price_acceleration > 0
    ):
        feature_amplification += 6

    if (
        breakout_pressure > 0
        and volume_ratio >= 1.0
        and candle_body_strength >= 0.40
    ):
        feature_amplification += 6

    if (
        ema_slope > 0
        and trend_strength > 0
        and range_position >= 0.45
    ):
        feature_amplification += 5

    transitional_structure_bonus = 0

    if (
        0.35 <= range_position <= 0.70
        and momentum_3 > 0
        and support_distance <= 0.06
    ):
        transitional_structure_bonus += 6

    if (
        price_acceleration > 0
        and momentum_3 > 0
        and breakout_pressure > -0.005
    ):
        transitional_structure_bonus += 6

    if (
        lower_wick_ratio > upper_wick_ratio
        and support_distance <= 0.06
        and rsi >= 38
    ):
        transitional_structure_bonus += 5

    if (
        ema_slope >= -0.003
        and trend_strength >= -0.005
        and momentum_5 > 0
    ):
        transitional_structure_bonus += 5

    if (
        0.002 <= atr_percent <= 0.035
        and volume_ratio >= 0.85
        and range_position >= 0.35
    ):
        transitional_structure_bonus += 4

    transitional_structure_bonus = min(
        transitional_structure_bonus,
        18
    )

    if transitional_structure_bonus > 0:
        print(
            f"TRANSITIONAL STRUCTURE SCORING | "
            f"bonus={transitional_structure_bonus:.2f}"
        )

    feature_amplification += transitional_structure_bonus

    feature_amplification = min(feature_amplification, 18)


    if feature_amplification > 0:
        print(
            f"FEATURE SCORING AMPLIFICATION | "
            f"bonus={feature_amplification:.2f}"
        )

    score += feature_amplification

    return min(score, 100)


def detect_macro_market_context(exchange):
    default_context = {
        "macro_regime": "macro_neutral",
        "risk_environment": "neutral",
        "risk_multiplier": 1.00,
        "score_adjustment": 0,
        "ai_adjustment": 0.00,
        "allow_new_longs": True,
        "allow_aggressive_entries": False,
        "capital_preservation": False,
        "altcoin_aggression": 1.00,
        "market_heat": 0.50,
        "reason": "neutral fallback context"
    }

    try:
        macro_symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"]
        macro_data = {}

        for macro_symbol in macro_symbols:
            try:
                raw_df = fetch(exchange, macro_symbol, limit=300)
                df = indicators(raw_df)

                if df.empty:
                    continue

                macro_data[macro_symbol] = df

            except Exception as fetch_error:
                print(f"MACRO: unable to fetch {macro_symbol}: {repr(fetch_error)}")

        if "BTC/USD" not in macro_data or "ETH/USD" not in macro_data:
            return default_context

        btc = macro_data["BTC/USD"]
        eth = macro_data["ETH/USD"]

        btc_last = btc.iloc[-1]
        eth_last = eth.iloc[-1]

        btc_close = float(btc_last["close"])
        btc_ema50 = float(btc_last["ema50"])
        btc_ema200 = float(btc_last["ema200"])
        btc_rsi = float(btc_last["rsi"])
        btc_trend_strength = float(btc_last.get("trend_strength", 0))
        btc_volatility = float(btc_last.get("volatility", 0))
        btc_atr_percent = float(btc_last.get("atr_percent", 0))
        btc_momentum_5 = float(btc_last.get("momentum_5", 0))
        btc_range_position = float(btc_last.get("range_position_20", 0.5))

        eth_trend_strength = float(eth_last.get("trend_strength", 0))
        eth_momentum_5 = float(eth_last.get("momentum_5", 0))

        btc_return_50 = (
            btc_close / float(btc["close"].tail(50).iloc[0])
        ) - 1

        participation_count = 0
        weakness_count = 0

        for _, df in macro_data.items():
            last = df.iloc[-1]

            close = float(last["close"])
            ema50 = float(last["ema50"])
            ema200 = float(last["ema200"])
            momentum_5 = float(last.get("momentum_5", 0))
            range_position = float(last.get("range_position_20", 0.5))

            if close > ema50 and ema50 > ema200 and momentum_5 > 0:
                participation_count += 1

            if close < ema50 or momentum_5 < 0 or range_position < 0.35:
                weakness_count += 1

        participation_ratio = participation_count / max(len(macro_data), 1)
        weakness_ratio = weakness_count / max(len(macro_data), 1)

        market_heat = (
            0.35 * participation_ratio +
            0.25 * max(0, min((btc_rsi - 35) / 35, 1)) +
            0.20 * max(0, min(btc_range_position, 1)) +
            0.20 * max(0, min((btc_momentum_5 + 0.05) / 0.10, 1))
        )

        market_heat = max(0.0, min(market_heat, 1.0))

        btc_bull_structure = (
            btc_close > btc_ema50 and
            btc_ema50 > btc_ema200 and
            btc_trend_strength > 0
        )

        btc_bear_structure = (
            btc_close < btc_ema50 and
            btc_ema50 < btc_ema200 and
            btc_trend_strength < 0
        )

        volatility_expanding = (
            btc_volatility >= 0.018 or
            btc_atr_percent >= 0.025
        )

        volatility_compressing = (
            btc_volatility <= 0.006 and
            btc_atr_percent <= 0.012
        )

        panic_event = (
            btc_return_50 <= -0.08 and
            volatility_expanding and
            weakness_ratio >= 0.60
        )

        distribution = (
            btc_close > btc_ema50 and
            btc_rsi >= 65 and
            btc_momentum_5 < 0 and
            weakness_ratio >= 0.50
        )

        accumulation = (
            btc_close < btc_ema200 and
            btc_rsi >= 38 and
            btc_momentum_5 > 0 and
            volatility_compressing
        )

        altseason_rotation = (
            eth_trend_strength > btc_trend_strength and
            eth_momentum_5 > btc_momentum_5 and
            participation_ratio >= 0.50 and
            btc_bull_structure
        )

        if panic_event:
            return {
                "macro_regime": "macro_panic_event",
                "risk_environment": "risk_off",
                "risk_multiplier": 0.00,
                "score_adjustment": 35,
                "ai_adjustment": 0.25,
                "allow_new_longs": False,
                "allow_aggressive_entries": False,
                "capital_preservation": True,
                "altcoin_aggression": 0.00,
                "market_heat": market_heat,
                "reason": "panic event detected across BTC and market breadth"
            }

        if btc_bear_structure and weakness_ratio >= 0.50:
            return {
                "macro_regime": "macro_bear_cycle",
                "risk_environment": "risk_off",
                "risk_multiplier": 0.25,
                "score_adjustment": 20,
                "ai_adjustment": 0.15,
                "allow_new_longs": True,
                "allow_aggressive_entries": False,
                "capital_preservation": True,
                "altcoin_aggression": 0.35,
                "market_heat": market_heat,
                "reason": "BTC bear structure with broad market weakness"
            }

        if distribution:
            return {
                "macro_regime": "macro_distribution",
                "risk_environment": "defensive",
                "risk_multiplier": 0.50,
                "score_adjustment": 15,
                "ai_adjustment": 0.10,
                "allow_new_longs": True,
                "allow_aggressive_entries": False,
                "capital_preservation": True,
                "altcoin_aggression": 0.60,
                "market_heat": market_heat,
                "reason": "rally showing internal weakness and momentum fade"
            }

        if altseason_rotation:
            return {
                "macro_regime": "macro_altseason_rotation",
                "risk_environment": "risk_on",
                "risk_multiplier": 1.25,
                "score_adjustment": -5,
                "ai_adjustment": -0.03,
                "allow_new_longs": True,
                "allow_aggressive_entries": True,
                "capital_preservation": False,
                "altcoin_aggression": 1.40,
                "market_heat": market_heat,
                "reason": "ETH and alt participation outperforming BTC structure"
            }

        if btc_bull_structure and participation_ratio >= 0.50 and market_heat >= 0.60:
            return {
                "macro_regime": "macro_bull_expansion",
                "risk_environment": "risk_on",
                "risk_multiplier": 1.20,
                "score_adjustment": -5,
                "ai_adjustment": -0.03,
                "allow_new_longs": True,
                "allow_aggressive_entries": True,
                "capital_preservation": False,
                "altcoin_aggression": 1.20,
                "market_heat": market_heat,
                "reason": "BTC bull structure with broad participation"
            }

        if accumulation:
            return {
                "macro_regime": "macro_accumulation",
                "risk_environment": "selective",
                "risk_multiplier": 0.75,
                "score_adjustment": 5,
                "ai_adjustment": 0.03,
                "allow_new_longs": True,
                "allow_aggressive_entries": False,
                "capital_preservation": False,
                "altcoin_aggression": 0.75,
                "market_heat": market_heat,
                "reason": "possible accumulation after compression and early momentum recovery"
            }

        if volatility_expanding:
            return {
                "macro_regime": "macro_volatility_expansion",
                "risk_environment": "cautious",
                "risk_multiplier": 0.65,
                "score_adjustment": 10,
                "ai_adjustment": 0.07,
                "allow_new_longs": True,
                "allow_aggressive_entries": False,
                "capital_preservation": True,
                "altcoin_aggression": 0.70,
                "market_heat": market_heat,
                "reason": "macro volatility expansion detected"
            }

        if volatility_compressing:
            return {
                "macro_regime": "macro_volatility_compression",
                "risk_environment": "selective",
                "risk_multiplier": 0.85,
                "score_adjustment": 5,
                "ai_adjustment": 0.03,
                "allow_new_longs": True,
                "allow_aggressive_entries": False,
                "capital_preservation": False,
                "altcoin_aggression": 0.85,
                "market_heat": market_heat,
                "reason": "macro volatility compression detected"
            }

        return default_context

    except Exception as macro_error:
        print(f"MACRO: context error: {repr(macro_error)}")
        return default_context


def apply_macro_to_regime(regime, macro_context):
    adjusted = regime.copy()

    if not macro_context.get("allow_new_longs", True):
        adjusted["allow_long"] = False
        adjusted["risk_multiplier"] = 0.0
        adjusted["reason"] = (
            adjusted["reason"] +
            " | macro block: " +
            macro_context["reason"]
        )
        return adjusted

    adjusted["risk_multiplier"] = (
        adjusted["risk_multiplier"] *
        macro_context.get("risk_multiplier", 1.0)
    )

    adjusted["risk_multiplier"] = max(
        0.0,
        min(adjusted["risk_multiplier"], 2.0)
    )

    adjusted["reason"] = (
        adjusted["reason"] +
        " | macro: " +
        macro_context["macro_regime"] +
        " | " +
        macro_context["reason"]
    )

    return adjusted


def detect_timeframe_alignment(main_df, higher_df, lower_df):
    main_indicators = indicators(main_df)
    higher_indicators = indicators(higher_df)
    lower_indicators = indicators(lower_df)

    if (
        main_indicators is None
        or higher_indicators is None
        or lower_indicators is None
        or main_indicators.empty
        or higher_indicators.empty
        or lower_indicators.empty
    ):
        return {
            "direction": "mixed",
            "aligned": False,
            "score_bonus": -3,
            "ai_bonus": -0.02,
            "reason": "insufficient timeframe data",
        }

    main_last = main_indicators.iloc[-1]
    higher_last = higher_indicators.iloc[-1]
    lower_last = lower_indicators.iloc[-1]

    main_bullish = (
        main_last["ema50"] > main_last["ema200"]
    )

    higher_bullish = (
        higher_last["ema50"] > higher_last["ema200"]
    )

    lower_bullish = (
        lower_last["ema50"] > lower_last["ema200"]
    )

    bullish_count = sum([
        main_bullish,
        higher_bullish,
        lower_bullish
    ])

    if bullish_count == 3:
        return {
            "aligned": True,
            "direction": "strong_bullish",
            "score_bonus": 15,
            "ai_bonus": 0.10
        }

    if bullish_count == 2:
        return {
            "aligned": True,
            "direction": "bullish",
            "score_bonus": 5,
            "ai_bonus": 0.05
        }

    return {
        "aligned": False,
        "direction": "mixed",
        "score_bonus": -3,
        "ai_bonus": -0.02
    }


def detect_market_regime(df):
    last = df.iloc[-1]
    recent = df.tail(50)

    close = float(last["close"])
    ema50 = float(last["ema50"])
    ema200 = float(last["ema200"])
    rsi = float(last["rsi"])
    trend_strength = float(last.get("trend_strength", 0))
    volume_ratio = float(last.get("volume_ratio", 1))

    recent_return = (close / float(recent["close"].iloc[0])) - 1
    recent_volatility = float(recent["return_1"].std())

    ema_bull = ema50 > ema200 and close > ema50
    ema_bear = ema50 < ema200 and close < ema50

    if recent_return <= -0.035 and recent_volatility >= 0.012:
        return {
            "regime": "crash_risk",
            "allow_long": False,
            "risk_multiplier": 0.0,
            "min_score": 999,
            "min_ai_prob": 0.99,
            "reason": "sharp downside move with high volatility"
        }

    if ema_bear and trend_strength < -0.012:
        return {
            "regime": "bear_trend",
            "allow_long": False,
            "risk_multiplier": 0.0,
            "min_score": 999,
            "min_ai_prob": 0.99,
            "reason": "ema50 below ema200 with weak structure"
        }

    if recent_volatility >= 0.018:
        return {
            "regime": "high_volatility",
            "allow_long": True,
            "risk_multiplier": 0.50,
            "min_score": 85,
            "min_ai_prob": 0.78,
            "reason": "high volatility, reduced position size"
        }

    if ema_bull and 45 <= rsi <= 70 and volume_ratio >= 0.85:
        return {
            "regime": "bull_trend",
            "allow_long": True,
            "risk_multiplier": 1.00,
            "min_score": 70,
            "min_ai_prob": 0.65,
            "reason": "bull trend confirmed"
        }

    return {
        "regime": "sideways_chop",
        "allow_long": True,
        "risk_multiplier": 0.50,
        "min_score": 85,
        "min_ai_prob": 0.75,
        "reason": "unclear trend, stricter entry required"
    }
def log_feature_regime_memory(symbol, regime_name, feature_importance_dict, pnl):
    if not feature_importance_dict:
        return

    file_exists = os.path.exists(FEATURE_REGIME_MEMORY_FILE)

    with open(FEATURE_REGIME_MEMORY_FILE, "a") as f:
        if not file_exists:
            f.write(
                "symbol,regime,feature,importance,pnl\n"
            )

        for feature, importance in feature_importance_dict.items():
            f.write(
                f"{symbol},"
                f"{regime_name},"
                f"{feature},"
                f"{importance},"
                f"{pnl}\n"
            )


def get_market_memory_score(symbol, regime_name, alignment_name):
    if not os.path.exists(MARKET_MEMORY_FILE):
        return 0

    try:
        df = pd.read_csv(MARKET_MEMORY_FILE)
    except Exception:
        return 0

    if df.empty:
        return 0

    filtered = df[
        (df["symbol"] == symbol) &
        (df["regime"] == regime_name) &
        (df["alignment"] == alignment_name)
    ]

    if len(filtered) < 5:
        return 0

    wins = filtered[filtered["result"] == "WIN"]

    win_rate = len(wins) / len(filtered)

    avg_pnl = filtered["pnl"].mean()

    memory_score = 0

    if win_rate >= 0.70:
        memory_score += 10

    elif win_rate <= 0.40:
        memory_score -= 10

    if avg_pnl > 0:
        memory_score += 5

    elif avg_pnl < 0:
        memory_score -= 5

    return max(-20, min(memory_score, 20))
def get_regime_feature_bias(symbol, regime_name):
    if not os.path.exists(FEATURE_REGIME_MEMORY_FILE):
        return {}

    try:
        df = pd.read_csv(FEATURE_REGIME_MEMORY_FILE)
    except Exception:
        return {}

    filtered = df[
        (df["symbol"] == symbol) &
        (df["regime"] == regime_name)
    ]

    if len(filtered) < 20:
        return {}

    grouped = (
        filtered
        .groupby("feature")
        .agg({
            "importance": "mean",
            "pnl": "mean"
        })
        .reset_index()
    )

    feature_bias = {}

    for _, row in grouped.iterrows():
        feature = row["feature"]
        importance = float(row["importance"])
        pnl = float(row["pnl"])

        score = 0

        if pnl > 0:
            score += 1

        if importance > 0.05:
            score += 1

        feature_bias[feature] = score

    return feature_bias

def get_dynamic_thresholds(performance, regime, macro_context=None, history_conf=0.50, timeframe_alignment=None):
    base_score = performance["score_threshold"]
    base_ai = performance["ai_threshold"]

    score_threshold = base_score
    ai_threshold = base_ai

    regime_name = regime["regime"]

    if regime_name == "bull_trend":
        score_threshold = max(base_score, 65)
        ai_threshold = max(base_ai, 0.38)

    elif regime_name == "sideways_chop":
        score_threshold = max(base_score, 62)
        ai_threshold = max(base_ai, 0.35)

    elif regime_name == "high_volatility":
        score_threshold = max(base_score, 80)
        ai_threshold = max(base_ai, 0.52)

    elif regime_name == "bear_trend":
        score_threshold = 999
        ai_threshold = 0.99

    elif regime_name == "crash_risk":
        score_threshold = 999
        ai_threshold = 0.99

    else:
        score_threshold = max(base_score, 75)
        ai_threshold = max(base_ai, 0.45)

    if macro_context is not None:
        macro_regime = macro_context.get("macro_regime", "macro_neutral")
        market_heat = macro_context.get("market_heat", 0.50)

        score_threshold += macro_context.get("score_adjustment", 0)
        ai_threshold += macro_context.get("ai_adjustment", 0.0)

        if macro_regime == "macro_bull_expansion":
            score_threshold -= 7
            ai_threshold -= 0.08

        elif macro_regime == "macro_altseason_rotation":
            score_threshold -= 10
            ai_threshold -= 0.10

        elif macro_regime == "macro_accumulation":
            score_threshold += 2
            ai_threshold -= 0.02

        elif macro_regime == "macro_volatility_compression":
            score_threshold -= 2
            ai_threshold -= 0.04

        elif macro_regime == "macro_volatility_expansion":
            score_threshold += 10
            ai_threshold += 0.05

        elif macro_regime == "macro_distribution":
            score_threshold += 14
            ai_threshold += 0.08

        elif macro_regime == "macro_bear_cycle":
            score_threshold += 22
            ai_threshold += 0.12

        elif macro_regime == "macro_panic_event":
            score_threshold = 999
            ai_threshold = 0.99

        if market_heat >= 0.70:
            score_threshold -= 5
            ai_threshold -= 0.05

        elif market_heat <= 0.30 and macro_regime != "macro_volatility_compression":
            score_threshold += 4
            ai_threshold += 0.02

    if timeframe_alignment is not None:
        alignment = timeframe_alignment.get("direction", "mixed")

        if alignment == "strong_bullish":
            score_threshold -= 5
            ai_threshold -= 0.05

        elif alignment == "bullish":
            score_threshold -= 2
            ai_threshold -= 0.03

        elif alignment == "mixed":
            score_threshold += 3
            ai_threshold += 0.02

    if history_conf >= 0.80:
        score_threshold -= 5
        ai_threshold -= 0.05

    elif history_conf >= 0.65:
        score_threshold -= 2
        ai_threshold -= 0.03

    elif history_conf < 0.45:
        score_threshold += 8
        ai_threshold += 0.06

    if performance["trade_count"] >= 25:
        if performance["win_rate"] >= 0.70 and performance["avg_pnl"] > 0:
            score_threshold -= 5
            ai_threshold -= 0.05

        elif performance["avg_pnl"] < 0:
            score_threshold += 5
            ai_threshold += 0.05

    cooldown_pressure = performance.get("cooldown_pressure", 0.0)

    if cooldown_pressure >= 0.30:
        score_threshold += int(cooldown_pressure * 3)
        ai_threshold += cooldown_pressure * 0.02

    if cooldown_pressure >= 0.60:
        score_threshold += int(cooldown_pressure * 10)
        ai_threshold += cooldown_pressure * 0.06

    if performance["loss_streak"] >= 6 and cooldown_pressure >= 0.95:
        score_threshold = 999
        ai_threshold = 0.99

    score_threshold = max(45, min(score_threshold, 999))
    ai_threshold = max(0.25, min(ai_threshold, 0.99))

    if score_threshold > 85:
        score_threshold = 85


    if ai_threshold > 0.60:
        ai_threshold = 0.60

    return round(score_threshold), round(ai_threshold, 2)

def explain_trade_decision(
    symbol,
    score,
    prob,
    history_conf,
    performance,
    regime,
    score_threshold,
    ai_threshold,
    macro_context
):
    reasons = []

    if score < score_threshold:
        reasons.append(
            f"score {score} below required {score_threshold}"
        )

    if prob < ai_threshold:
        reasons.append(
            f"AI probability {prob:.2f} below required {ai_threshold:.2f}"
        )

    if history_conf < 0.45:
        reasons.append(
            f"history confidence {history_conf:.2f} below required 0.45"
        )

    if not regime["allow_long"]:
        reasons.append(
            f"market regime blocked long entries: {regime['regime']}"
        )

    if performance["paused"]:
        reasons.append(
            f"symbol paused from loss streak {performance['loss_streak']}"
        )

    if not macro_context.get("allow_new_longs", True):
        reasons.append("macro regime blocks new long exposure")

    if not reasons:
        print(f"{symbol}: ENTRY CONDITIONS PASSED")
        return

    print(f"{symbol}: NO TRADE because " + " | ".join(reasons))

def log_execution_journal(
    username,
    symbol,
    decision,
    reason,
    score=None,
    score_required=None,
    prob=None,
    prob_required=None,
    opportunity_rank=None,
    macro_regime=None,
    regime=None,
    sync_state=None,
    risk_multiplier=None,
    cash=None
):
    file_exists = os.path.exists(EXECUTION_JOURNAL_FILE)

    row = {
        "time": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "symbol": symbol,
        "decision": decision,
        "reason": reason,
        "score": score,
        "score_required": score_required,
        "prob": prob,
        "prob_required": prob_required,
        "opportunity_rank": opportunity_rank,
        "macro_regime": macro_regime,
        "regime": regime,
        "sync_state": sync_state,
        "risk_multiplier": risk_multiplier,
        "cash": cash
    }

    pd.DataFrame([row]).to_csv(
        EXECUTION_JOURNAL_FILE,
        mode="a",
        header=not file_exists,
        index=False
    )

def log_trade_result(
    username,
    symbol,
    entry,
    exit_price,
    amount,
    score,
    prob,
    exit_reason="UNKNOWN"
):
    pnl = (exit_price - entry) * amount
    result = "WIN" if pnl > 0 else "LOSS"

    file_exists = os.path.exists(TRADE_RESULTS_FILE)

    with open(TRADE_RESULTS_FILE, "a") as f:
        if not file_exists:
            f.write(
                "username,symbol,entry,exit,amount,score,prob,pnl,result,exit_reason\n"
            )

        f.write(
            f"{username},{symbol},{entry},{exit_price},{amount},"
            f"{score},{prob},{pnl},{result},{exit_reason}\n"
        )


def log_market_memory(
    symbol,
    regime,
    alignment,
    score,
    prob,
    pnl,
    result
):
    file_exists = os.path.exists(MARKET_MEMORY_FILE)

    with open(MARKET_MEMORY_FILE, "a") as f:
        if not file_exists:
            f.write(
                "symbol,regime,alignment,score,prob,pnl,result\n"
            )

        f.write(
            f"{symbol},"
            f"{regime},"
            f"{alignment},"
            f"{score},"
            f"{prob},"
            f"{pnl},"
            f"{result}\n"
        )

def trade_history_confidence(symbol):
    if not os.path.exists(TRADE_RESULTS_FILE):
        return 0.50

    try:
        df = pd.read_csv(TRADE_RESULTS_FILE)
    except Exception:
        return 0.50

    if df.empty:
        return 0.50

    symbol_df = df[df["symbol"] == symbol].tail(75).copy()

    if len(symbol_df) < 5:
        return 0.50

    symbol_df["weight"] = np.linspace(0.30, 1.00, len(symbol_df))

    symbol_df["win_value"] = symbol_df["result"].apply(
        lambda result: 1 if result == "WIN" else 0
    )

    weighted_win_rate = (
        (symbol_df["win_value"] * symbol_df["weight"]).sum() /
        symbol_df["weight"].sum()
    )

    weighted_avg_pnl = (
        (symbol_df["pnl"] * symbol_df["weight"]).sum() /
        symbol_df["weight"].sum()
    )

    confidence = weighted_win_rate

    if weighted_avg_pnl > 0:
        confidence += 0.10
    else:
        confidence -= 0.10

    return max(0.10, min(confidence, 0.90))

def is_symbol_on_cooldown(state, username, symbol):
    cooldowns = state.get("cooldowns", {})
    user_cooldowns = cooldowns.get(username, {})
    cooldown_until = user_cooldowns.get(symbol)

    if cooldown_until is None:
        return False

    now = time.time()

    return now < cooldown_until

def set_symbol_cooldown(state, username, symbol):
    if "cooldowns" not in state:
        state["cooldowns"] = {}

    if username not in state["cooldowns"]:
        state["cooldowns"][username] = {}

    state["cooldowns"][username][symbol] = time.time() + COOLDOWN_SECONDS
def get_symbol_performance(symbol):
    default = {
        "trade_count": 0,
        "win_rate": 0.50,
        "avg_pnl": 0,
        "loss_streak": 0,
        "cooldown_pressure": 0.0,
        "ai_threshold": AI_THRESHOLD,
        "score_threshold": BASE_SCORE_THRESHOLD,
        "paused": False
    }

    if not os.path.exists(TRADE_RESULTS_FILE):
        return default

    try:
        df = pd.read_csv(TRADE_RESULTS_FILE)
    except Exception:
        return default

    symbol_df = df[df["symbol"] == symbol].tail(75).copy()

    if symbol_df.empty:
        return default

    trade_count = len(symbol_df)

    symbol_df["weight"] = np.linspace(0.30, 1.00, trade_count)

    symbol_df["win_value"] = symbol_df["result"].apply(
        lambda result: 1 if result == "WIN" else 0
    )

    win_rate = (
        (symbol_df["win_value"] * symbol_df["weight"]).sum() /
        symbol_df["weight"].sum()
    )

    avg_pnl = (
        (symbol_df["pnl"] * symbol_df["weight"]).sum() /
        symbol_df["weight"].sum()
    )

    recent_results = symbol_df["result"].tail(10).tolist()

    loss_streak = 0

    for result in reversed(recent_results):
        if result == "LOSS":
            loss_streak += 1
        else:
            break

    cooldown_pressure = 0.0

    if loss_streak >= 1:
        cooldown_pressure += loss_streak * 0.15

    if win_rate < 0.45:
        cooldown_pressure += 0.30

    if avg_pnl < 0:
        cooldown_pressure += 0.30

    if win_rate >= 0.70 and avg_pnl > 0:
        cooldown_pressure -= 0.35

    elif win_rate >= 0.60 and avg_pnl > 0:
        cooldown_pressure -= 0.20

    cooldown_pressure = max(0.0, min(cooldown_pressure, 1.0))

    ai_threshold = AI_THRESHOLD
    score_threshold = BASE_SCORE_THRESHOLD
    paused = False

    if trade_count >= 5:
        if win_rate >= 0.60 and avg_pnl > 0:
            ai_threshold = max(MIN_AI_THRESHOLD, AI_THRESHOLD - 0.05)
            score_threshold = max(50, BASE_SCORE_THRESHOLD - 5)

        elif win_rate <= 0.40 or avg_pnl < 0:
            ai_threshold = min(MAX_AI_THRESHOLD, AI_THRESHOLD + 0.10)
            score_threshold = BASE_SCORE_THRESHOLD + 10

    if cooldown_pressure >= 0.95 and loss_streak >= 6:
        paused = True

    return {
        "trade_count": int(trade_count),
        "win_rate": float(win_rate),
        "avg_pnl": float(avg_pnl),
        "loss_streak": int(loss_streak),
        "cooldown_pressure": float(cooldown_pressure),
        "ai_threshold": float(ai_threshold),
        "score_threshold": int(score_threshold),
        "paused": bool(paused)
    }



def calculate_dynamic_risk_multiplier(score, prob, history_conf, regime, memory_score, timeframe_alignment):
    multiplier = 1.0

    if score >= 80:
        multiplier += 0.40
    elif score >= 70:
        multiplier += 0.20
    elif score < 50:
        multiplier -= 0.30

    if prob >= 0.75:
        multiplier += 0.40
    elif prob >= 0.60:
        multiplier += 0.20
    elif prob < 0.40:
        multiplier -= 0.30

    if history_conf >= 0.75:
        multiplier += 0.20
    elif history_conf < 0.45:
        multiplier -= 0.40

    if memory_score >= 10:
        multiplier += 0.20
    elif memory_score <= -10:
        multiplier -= 0.30

    if timeframe_alignment["direction"] == "strong_bullish":
        multiplier += 0.30
    elif timeframe_alignment["direction"] == "bullish":
        multiplier += 0.15
    elif timeframe_alignment["direction"] == "mixed":
        multiplier -= 0.30

    if regime["regime"] == "sideways_chop":
        multiplier -= 0.20
    elif regime["regime"] == "high_volatility":
        multiplier -= 0.30
    elif regime["regime"] == "bull_trend":
        multiplier += 0.20

    multiplier = max(0.20, min(multiplier, 1.75))

    return multiplier


def calculate_position_size(usd_balance, risk, entry_price):
    risk_dollars = usd_balance * risk

    stop_price = entry_price * STOP_LOSS
    risk_per_coin = entry_price - stop_price

    if risk_per_coin <= 0:
        return 0

    raw_amount = risk_dollars / risk_per_coin

    max_position_value = usd_balance * 0.10
    max_amount = max_position_value / entry_price

    amount = min(raw_amount, max_amount)

    return round(amount, 8)

def calculate_opportunity_rank(
    score,
    prob,
    regime,
    macro_context,
    timeframe_alignment,
    memory_score,
    history_conf=0.50,
    cooldown_pressure=0.0
):
    rank = 0.0
    signal_amplification = 0.0

    rank += score * 0.36
    rank += prob * 100 * 0.26
    rank += history_conf * 100 * 0.12

    alignment = timeframe_alignment.get("direction", "mixed")
    regime_name = regime.get("regime", "unknown")
    macro_regime = macro_context.get("macro_regime", "macro_neutral")
    market_heat = macro_context.get("market_heat", 0.50)

    if alignment == "strong_bullish":
        rank += 12
        signal_amplification += 8

    elif alignment == "bullish":
        rank += 7
        signal_amplification += 4

    elif alignment == "mixed":
        rank -= 6

    if regime_name == "bull_trend":
        rank += 8
        signal_amplification += 8

    elif regime_name == "sideways_chop":
        rank -= 2

        if prob >= 0.25:
            signal_amplification += 4

    elif regime_name == "high_volatility":
        rank -= 8

    elif regime_name in ["bear_trend", "crash_risk"]:
        rank -= 30

    rank += market_heat * 10

    if macro_regime == "macro_bull_expansion":
        rank += 10
        signal_amplification += 8

    elif macro_regime == "macro_altseason_rotation":
        rank += 12
        signal_amplification += 10

    elif macro_regime == "macro_accumulation":
        rank += 4
        signal_amplification += 3

    elif macro_regime == "macro_volatility_compression":
        rank -= 1

        if regime_name == "sideways_chop" and prob >= 0.25:
            signal_amplification += 5

    elif macro_regime == "macro_volatility_expansion":
        rank -= 6

    elif macro_regime == "macro_distribution":
        rank -= 10

    elif macro_regime == "macro_bear_cycle":
        rank -= 18

    elif macro_regime == "macro_panic_event":
        rank = 0
        signal_amplification = 0

    if prob >= 0.75:
        signal_amplification += 10

    elif prob >= 0.65:
        signal_amplification += 6

    elif prob >= 0.55:
        signal_amplification += 3

    elif prob >= 0.35 and regime_name == "sideways_chop":
        signal_amplification += 2

    if history_conf >= 0.85 and cooldown_pressure <= 0.30:
        signal_amplification += 4

    if (
        regime_name == "sideways_chop"
        and macro_regime == "macro_volatility_compression"
        and alignment in ["mixed", "bullish"]
        and prob >= 0.25
    ):
        signal_amplification += 6

    signal_amplification = min(signal_amplification, 12)
    rank += signal_amplification

    rank -= cooldown_pressure * 16

    if signal_amplification > 0:
        print(
            f"SIGNAL AMPLIFICATION | "
            f"bonus={signal_amplification:.2f} | "
            f"regime={regime_name} | "
            f"alignment={alignment} | "
            f"prob={prob:.2f} | "
            f"macro={macro_regime}"
        )

    if not regime.get("allow_long", False):
        rank = 0

    if not macro_context.get("allow_new_longs", True):
        rank = 0

    return round(max(0, min(rank, 100)), 2)

def get_latest_symbol_price(exchange, symbol):
    try:
        df = fetch(exchange, symbol, limit=50)

        if df.empty:
            return None

        return float(df["close"].iloc[-1])

    except Exception as price_error:
        print(f"{symbol}: unable to fetch latest rotation price: {repr(price_error)}")
        return None


def find_weakest_open_position(user_positions):
    weakest_symbol = None
    weakest_rank = 999

    for held_symbol, position in user_positions.items():
        position_rank = float(position.get("opportunity_rank", 50))

        if position_rank < weakest_rank:
            weakest_rank = position_rank
            weakest_symbol = held_symbol

    return weakest_symbol, weakest_rank

def get_base_asset(symbol):
    if not symbol:
        return ""

    return str(symbol).split("/")[0].upper().strip()


def has_existing_base_asset_exposure(symbol, user_positions):
    candidate_base = get_base_asset(symbol)

    for open_symbol in user_positions.keys():
        if get_base_asset(open_symbol) == candidate_base:
            return True, open_symbol

    return False, None


def should_rotate_capital(candidate_rank, weakest_rank):
    rank_edge = candidate_rank - weakest_rank

    if candidate_rank < 55:
        return False

    if weakest_rank <= 20 and rank_edge >= 15:
        return True

    if weakest_rank <= 40 and rank_edge >= 12:
        return True

    if weakest_rank <= 60 and candidate_rank >= 65 and rank_edge >= 8:
        return True

    if candidate_rank >= 75 and rank_edge >= 6:
        return True

    return False


def get_symbol_sector(symbol):
    base = symbol.split("/")[0].upper()

    sector_map = {
        "BTC": "bitcoin",
        "ETH": "layer1",
        "SOL": "layer1",
        "ADA": "layer1",
        "XRP": "payments",
        "XLM": "payments",
        "DOGE": "meme",
        "SHIB": "meme",
        "AVAX": "layer1",
        "DOT": "layer1",
        "LINK": "oracle",
        "UNI": "defi",
        "AAVE": "defi",
        "ICP": "infrastructure",
        "HBAR": "enterprise",
        "ALGO": "payments",
        "HBAR": "enterprise",
        "XDC": "enterprise",
        "AAVE": "defi",
        "CRV": "defi",
        "CVX": "defi",
        "AKT": "infrastructure",
        "ICP": "infrastructure",
        "AI": "ai",
        "FET": "ai",
        "TAO": "ai",
        "BONK": "meme",
        "PEPE": "meme",
        "ATOM": "interoperability",
    }

    return sector_map.get(base, "other")


def calculate_sector_exposure(user_positions):
    exposure = {}

    for held_symbol in user_positions:
        sector = get_symbol_sector(held_symbol)
        exposure[sector] = exposure.get(sector, 0) + 1

    return exposure


def calculate_correlation_risk(candidate_symbol, user_positions):
    candidate_sector = get_symbol_sector(candidate_symbol)

    if not user_positions:
        return 0.0

    same_sector_count = 0

    for held_symbol in user_positions:
        held_sector = get_symbol_sector(held_symbol)

        if held_sector == candidate_sector:
            same_sector_count += 1

    correlation_risk = same_sector_count / max(len(user_positions), 1)

    return max(0.0, min(correlation_risk, 1.0))

def evaluate_sector_allocation(candidate_symbol, user_positions, opportunity_rank):
    candidate_sector = get_symbol_sector(candidate_symbol)
    sector_exposure = calculate_sector_exposure(user_positions)
    sector_count = sector_exposure.get(candidate_sector, 0)
    correlation_risk = calculate_correlation_risk(
        candidate_symbol,
        user_positions
    )

    allow_sector_entry = True
    reason = "sector exposure acceptable"

    if sector_count >= MAX_SAME_SECTOR_POSITIONS:
        if (
            candidate_sector == "other"
            and opportunity_rank >= 45
        ):
            allow_sector_entry = True
            reason = (
                "same-sector limit relaxed for strong other-sector opportunity"
            )

        elif opportunity_rank >= MIN_SECTOR_ROTATION_RANK:
            allow_sector_entry = True
            reason = (
                "same-sector limit relaxed for high-rank opportunity"
            )

        else:
            allow_sector_entry = False
            reason = "same-sector exposure limit reached"

    if (
        correlation_risk >= MAX_CORRELATION_RISK
        and opportunity_rank < MIN_SECTOR_ROTATION_RANK
    ):
        allow_sector_entry = False
        reason = "correlation risk too high for current opportunity rank"

    return {
        "sector": candidate_sector,
        "sector_count": sector_count,
        "sector_exposure": sector_exposure,
        "correlation_risk": correlation_risk,
        "allow_sector_entry": allow_sector_entry,
        "reason": reason
    }


def forecast_market_regime(df, macro_context, regime):
    last = df.iloc[-1]

    rsi = float(last.get("rsi", 50))
    volume_ratio = float(last.get("volume_ratio", 1.0))
    trend_strength = float(last.get("trend_strength", 0))
    breakout_pressure = float(last.get("breakout_pressure_20", 0))
    price_acceleration = float(last.get("price_acceleration", 0))
    momentum_3 = float(last.get("momentum_3", 0))
    momentum_5 = float(last.get("momentum_5", 0))
    range_position = float(last.get("range_position_20", 0.5))
    volatility = float(last.get("atr_ratio", 0))
    ema_slope = float(last.get("ema_slope", 0))
    compression_environment = (
        0.30 <= range_position <= 0.70
        and volatility <= 0.05
    )

    breakout_probability = 0.0
    expansion_probability = 0.0
    panic_probability = 0.0
    exhaustion_probability = 0.0
    altseason_probability = 0.0

    if breakout_pressure > 0:
        breakout_probability += 0.20

    if volume_ratio > 1.2:
        breakout_probability += 0.20

    if momentum_3 > 0:
        breakout_probability += 0.10

    if momentum_5 > 0:
        breakout_probability += 0.10

    if ema_slope > 0:
        breakout_probability += 0.10

    if range_position >= 0.70:
        breakout_probability += 0.10

    if trend_strength > 0:
        expansion_probability += 0.20

    if momentum_3 > 0:
        expansion_probability += 0.15

    if momentum_5 > 0:
        expansion_probability += 0.15

    if volume_ratio > 1.0:
        expansion_probability += 0.10

    if ema_slope > 0:
        expansion_probability += 0.10

    if volatility > 0.03:
        expansion_probability += 0.10

    if compression_environment:
        breakout_probability += 0.10
        expansion_probability += 0.08


    if momentum_3 < 0:
        if compression_environment:
            panic_probability += 0.08
        else:
            panic_probability += 0.20

    if momentum_5 < 0:
        if compression_environment:
            panic_probability += 0.08
        else:
            panic_probability += 0.20

    if ema_slope < 0:
        if compression_environment:
            panic_probability += 0.08
        else:
            panic_probability += 0.20

    if range_position < 0.25:
        panic_probability += 0.10

    if trend_strength < 0:
        if compression_environment:
            panic_probability += 0.05
        else:
            panic_probability += 0.10

    if volatility > 0.05:
        panic_probability += 0.15

    if rsi >= 72:
        exhaustion_probability += 0.25

    if range_position >= 0.90:
        exhaustion_probability += 0.20

    if breakout_pressure < 0:
        exhaustion_probability += 0.15

    if price_acceleration < 0:
        exhaustion_probability += 0.15

    if macro_context["macro_regime"] == "macro_altseason_rotation":
        altseason_probability += 0.40

    if macro_context["market_heat"] >= 0.60:
        altseason_probability += 0.20

    if regime["regime"] == "bull_trend":
        altseason_probability += 0.20

    if momentum_3 > 0 and momentum_5 > 0:
        altseason_probability += 0.10

    breakout_probability = max(0, min(breakout_probability, 1))
    expansion_probability = max(0, min(expansion_probability, 1))
    panic_probability = max(0, min(panic_probability, 1))
    exhaustion_probability = max(0, min(exhaustion_probability, 1))
    altseason_probability = max(0, min(altseason_probability, 1))

    next_regime = "neutral"

    if panic_probability >= PANIC_FORECAST_THRESHOLD:
        next_regime = "panic_risk"

    elif breakout_probability >= BREAKOUT_FORECAST_THRESHOLD:
        next_regime = "breakout_expansion"

    elif expansion_probability >= 0.65:
        next_regime = "trend_expansion"

    elif exhaustion_probability >= 0.65:
        next_regime = "trend_exhaustion"

    probability_total = (
        breakout_probability +
        expansion_probability +
        panic_probability +
        exhaustion_probability +
        altseason_probability
    )

    if probability_total > 0:
        breakout_probability /= probability_total
        expansion_probability /= probability_total
        panic_probability /= probability_total
        exhaustion_probability /= probability_total
        altseason_probability /= probability_total

    forecast_confidence = max(
        breakout_probability,
        expansion_probability,
        panic_probability,
        exhaustion_probability,
        altseason_probability
    )

    return {
        "next_regime": next_regime,
        "forecast_confidence": round(forecast_confidence, 2),
        "breakout_probability": round(breakout_probability, 2),
        "expansion_probability": round(expansion_probability, 2),
        "panic_probability": round(panic_probability, 2),
        "exhaustion_probability": round(exhaustion_probability, 2),
        "altseason_probability": round(altseason_probability, 2)
    }

def log_forecast_memory(symbol, macro_context, regime, forecast):
    file_exists = os.path.exists(FORECAST_MEMORY_FILE)

    with open(FORECAST_MEMORY_FILE, "a") as f:
        if not file_exists:
            f.write(
                "time,symbol,macro_regime,local_regime,next_regime,"
                "confidence,breakout,expansion,panic,exhaustion,altseason\n"
            )

        f.write(
            f"{datetime.now().isoformat()},"
            f"{symbol},"
            f"{macro_context.get('macro_regime', 'unknown')},"
            f"{regime.get('regime', 'unknown')},"
            f"{forecast.get('next_regime', 'neutral')},"
            f"{forecast.get('forecast_confidence', 0)},"
            f"{forecast.get('breakout_probability', 0)},"
            f"{forecast.get('expansion_probability', 0)},"
            f"{forecast.get('panic_probability', 0)},"
            f"{forecast.get('exhaustion_probability', 0)},"
            f"{forecast.get('altseason_probability', 0)}\n"
        )


def get_forecast_transition_signal(symbol):
    default = {
        "transition_state": "insufficient_memory",
        "breakout_trend": "unknown",
        "expansion_trend": "unknown",
        "panic_trend": "unknown",
        "exhaustion_trend": "unknown",
        "altseason_trend": "unknown",
        "rank_adjustment": 0,
        "risk_adjustment": 1.00,
        "confidence": 0.0,
        "reason": "not enough forecast history"
    }

    if not os.path.exists(FORECAST_MEMORY_FILE):
        return default

    try:
        memory_df = pd.read_csv(FORECAST_MEMORY_FILE)
    except Exception:
        return default

    if memory_df.empty:
        return default

    symbol_df = memory_df[
        memory_df["symbol"] == symbol
    ].tail(12).copy()

    if len(symbol_df) < 4:
        return default

    for column in [
        "confidence",
        "breakout",
        "expansion",
        "panic",
        "exhaustion",
        "altseason"
    ]:
        symbol_df[column] = pd.to_numeric(
            symbol_df[column],
            errors="coerce"
        ).fillna(0)

    recent = symbol_df.tail(4)

    older = symbol_df.head(
        max(len(symbol_df) - 4, 1)
    )

    recent_breakout = recent["breakout"].mean()
    older_breakout = older["breakout"].mean()

    recent_expansion = recent["expansion"].mean()
    older_expansion = older["expansion"].mean()

    recent_panic = recent["panic"].mean()
    older_panic = older["panic"].mean()

    recent_exhaustion = recent["exhaustion"].mean()
    older_exhaustion = older["exhaustion"].mean()

    recent_altseason = recent["altseason"].mean()
    older_altseason = older["altseason"].mean()

    breakout_delta = recent_breakout - older_breakout
    expansion_delta = recent_expansion - older_expansion
    panic_delta = recent_panic - older_panic
    exhaustion_delta = recent_exhaustion - older_exhaustion
    altseason_delta = recent_altseason - older_altseason

    def classify_delta(delta):
        if delta >= 0.12:
            return "rising"

        if delta <= -0.12:
            return "fading"

        return "stable"

    breakout_trend = classify_delta(
        breakout_delta
    )

    expansion_trend = classify_delta(
        expansion_delta
    )

    panic_trend = classify_delta(
        panic_delta
    )

    exhaustion_trend = classify_delta(
        exhaustion_delta
    )

    altseason_trend = classify_delta(
        altseason_delta
    )

    rank_adjustment = 0
    risk_adjustment = 1.00
    transition_state = "stable"

    reason_parts = []

    if breakout_trend == "rising":
        rank_adjustment += 5
        risk_adjustment += 0.05
        transition_state = "breakout_building"
        reason_parts.append(
            "breakout probability rising"
        )

    if expansion_trend == "rising":
        rank_adjustment += 4
        risk_adjustment += 0.05
        transition_state = "expansion_building"
        reason_parts.append(
            "expansion probability rising"
        )

    if altseason_trend == "rising":
        rank_adjustment += 4
        risk_adjustment += 0.05
        transition_state = "altseason_building"
        reason_parts.append(
            "altseason probability rising"
        )

    if panic_trend == "rising":
        rank_adjustment -= 10
        risk_adjustment -= 0.20
        transition_state = "panic_risk_building"
        reason_parts.append(
            "panic probability rising"
        )

    if exhaustion_trend == "rising":
        rank_adjustment -= 6
        risk_adjustment -= 0.10
        transition_state = "exhaustion_building"
        reason_parts.append(
            "exhaustion probability rising"
        )

    if not reason_parts:
        reason_parts.append(
            "forecast probabilities stable"
        )

    confidence = float(
        recent["confidence"].mean()
    )

    risk_adjustment = max(
        0.50,
        min(risk_adjustment, 1.25)
    )

    return {
        "transition_state": transition_state,
        "breakout_trend": breakout_trend,
        "expansion_trend": expansion_trend,
        "panic_trend": panic_trend,
        "exhaustion_trend": exhaustion_trend,
        "altseason_trend": altseason_trend,
        "rank_adjustment": rank_adjustment,
        "risk_adjustment": risk_adjustment,
        "confidence": round(confidence, 2),
        "reason": " | ".join(reason_parts)
    }

def log_global_market_state(
    symbol,
    macro_context,
    forecast,
    transition_signal
):
    file_exists = os.path.exists(GLOBAL_MARKET_MEMORY_FILE)

    with open(GLOBAL_MARKET_MEMORY_FILE, "a") as f:
        if not file_exists:
            f.write(
                "time,symbol,macro_regime,next_regime,"
                "forecast_confidence,breakout,expansion,"
                "panic,exhaustion,altseason,"
                "transition_state\n"
            )

        f.write(
            f"{datetime.now().isoformat()},"
            f"{symbol},"
            f"{macro_context.get('macro_regime', 'unknown')},"
            f"{forecast.get('next_regime', 'neutral')},"
            f"{forecast.get('forecast_confidence', 0)},"
            f"{forecast.get('breakout_probability', 0)},"
            f"{forecast.get('expansion_probability', 0)},"
            f"{forecast.get('panic_probability', 0)},"
            f"{forecast.get('exhaustion_probability', 0)},"
            f"{forecast.get('altseason_probability', 0)},"
            f"{transition_signal.get('transition_state', 'unknown')}\n"
        )

def analyze_global_market_synchronization():
    default = {
        "market_state": "neutral",
        "risk_mode": "balanced",
        "synchronization_score": 0.0,
        "rank_adjustment": -6,
        "risk_adjustment": 0.85,
        "reason": "insufficient global memory"
    }

    if not os.path.exists(GLOBAL_MARKET_MEMORY_FILE):
        return default

    try:
        df = pd.read_csv(GLOBAL_MARKET_MEMORY_FILE)
    except Exception:
        return default

    if df.empty:
        return default

    recent = df.tail(30).copy()

    if len(recent) < 10:
        return default

    numeric_columns = [
        "forecast_confidence",
        "breakout",
        "expansion",
        "panic",
        "exhaustion",
        "altseason"
    ]

    for column in numeric_columns:
        recent[column] = pd.to_numeric(
            recent[column],
            errors="coerce"
        ).fillna(0)

    avg_panic = recent["panic"].mean()
    avg_exhaustion = recent["exhaustion"].mean()
    avg_altseason = recent["altseason"].mean()

    bullish_alignment = 0
    bearish_alignment = 0

    for _, row in recent.iterrows():
        if (
            row["breakout"] >= 0.60 or
            row["expansion"] >= 0.60
        ):
            bullish_alignment += 1

        if (
            row["panic"] >= 0.60 or
            row["exhaustion"] >= 0.60
        ):
            bearish_alignment += 1

    total = max(len(recent), 1)

    bullish_sync = bullish_alignment / total
    bearish_sync = bearish_alignment / total

    synchronization_score = abs(
        bullish_sync - bearish_sync
    )

    market_state = "neutral"
    risk_mode = "balanced"
    rank_adjustment = 0
    risk_adjustment = 1.00
    reasons = []

    if bullish_sync >= 0.55:
        market_state = "global_risk_on"
        risk_mode = "aggressive"
        rank_adjustment += 8
        risk_adjustment += 0.15
        reasons.append("broad bullish synchronization detected")

    if bearish_sync >= 0.55:
        market_state = "global_risk_off"
        risk_mode = "defensive"

        compression_environment = (
            0.35 <= synchronization_score <= 0.65
        )

        if compression_environment:
            rank_adjustment -= 5
            risk_adjustment -= 0.15
            reasons.append(
                "broad bearish synchronization detected "
                "(normalized for compression environment)"
            )

        else:
            rank_adjustment -= 12
            risk_adjustment -= 0.25
            reasons.append("broad bearish synchronization detected")

    if avg_altseason >= 0.50:
        market_state = "altseason_expansion"
        rank_adjustment += 6
        risk_adjustment += 0.10
        reasons.append("altseason synchronization strengthening")

    if avg_panic >= 0.70:
        market_state = "market_panic_transition"
        rank_adjustment -= 18
        risk_adjustment -= 0.35
        reasons.append("market-wide panic synchronization detected")

    if avg_exhaustion >= 0.60:
        rank_adjustment -= 4
        risk_adjustment -= 0.05
        reasons.append(
            "market exhaustion synchronization detected "
            "(normalized)"
        )

    risk_adjustment = max(
        0.40,
        min(risk_adjustment, 1.35)
    )

    synchronization_score = round(
        synchronization_score,
        2
    )

    return {
        "market_state": market_state,
        "risk_mode": risk_mode,
        "synchronization_score": synchronization_score,
        "rank_adjustment": int(rank_adjustment),
        "risk_adjustment": float(risk_adjustment),
        "reason": " | ".join(reasons) if reasons else "market synchronization neutral"
    }




def get_adaptive_trade_targets(df, regime):
    last = df.iloc[-1]

    atr_percent = float(last.get("atr_percent", 0.01))
    volatility = float(last.get("volatility", 0.01))

    regime_name = regime["regime"]

    stop_loss_percent = 0.015
    partial_tp_percent = 0.025
    trail_start_percent = 0.035
    trail_distance_percent = 0.015

    if regime_name == "strong_bullish":
        partial_tp_percent = 0.05
        trail_start_percent = 0.06
        trail_distance_percent = 0.02

    elif regime_name == "bull_trend":
        partial_tp_percent = 0.04
        trail_start_percent = 0.05

    elif regime_name == "sideways_chop":
        stop_loss_percent = 0.015
        partial_tp_percent = 0.025
        trail_start_percent = 0.03
        trail_distance_percent = 0.015

    if atr_percent > 0.025:
        stop_loss_percent += 0.01
        partial_tp_percent += 0.02
        trail_distance_percent += 0.01

    if volatility > 0.03:
        stop_loss_percent += 0.005

    return {
        "sl_multiplier": 1 - stop_loss_percent,
        "partial_tp_multiplier": 1 + partial_tp_percent,
        "trail_start_multiplier": 1 + trail_start_percent,
        "trail_distance": trail_distance_percent
    }
# ===== SIMPLE EVOLUTION =====

def generate_strategy():
    return {
        "rsi_low": random.randint(40, 50),
        "rsi_high": random.randint(55, 70)
    }

def evaluate(df, strat):
    labelled = df.dropna(subset=["target"])
    validation = labelled.iloc[int(len(labelled) * 0.70):]
    selected = validation[
        validation["rsi"].between(
            strat["rsi_low"],
            strat["rsi_high"],
            inclusive="neither"
        )
    ]
    if len(selected) < 10:
        return -1.0

    win_rate = float(selected["target"].mean())
    coverage = min(len(selected) / max(len(validation), 1), 0.50)
    return win_rate - 0.50 + (coverage * 0.05)

def evolve(df):
    best = None
    best_score = float("-inf")

    for _ in range(20):
        strat = generate_strategy()
        score = evaluate(df, strat)
        if score > best_score:
            best = strat
            best_score = score

    if best is None:
        best = {"rsi_low": 42, "rsi_high": 65}

    atomic_json_write(STRATEGY_FILE, best)

    return best

def load_strategy(df):
    if not os.path.exists(STRATEGY_FILE) or os.path.getsize(STRATEGY_FILE) == 0:
        return evolve(df)

    try:
        with open(STRATEGY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return evolve(df)

# ===== LOGGING =====
def log_trade(username, symbol, entry, exit_price, amount):
    pnl = (exit_price - entry) * amount
    row = pd.DataFrame([{
        "time": pd.Timestamp.now(),
        "username": username,
        "symbol": symbol,
        "entry": entry,
        "exit": exit_price,
        "amount": amount,
        "pnl": pnl,
        "result": 1 if pnl > 0 else 0
    }])
    row.to_csv(TRADES_FILE, mode='a', header=False, index=False)



def log_daily_pnl_summary():
    if not os.path.exists(TRADES_FILE):
        logging.info("Daily PnL Summary | no trades file found yet")
        return

    try:
        df = pd.read_csv(TRADES_FILE)

        if df.empty:
            logging.info("Daily PnL Summary | no closed trades yet")
            return

        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"])

        today = pd.Timestamp.now().date()
        today_df = df[df["time"].dt.date == today]

        if today_df.empty:
            logging.info("Daily PnL Summary | no closed trades today")
            return

        total_pnl = today_df["pnl"].sum()
        total_trades = len(today_df)
        wins = (today_df["pnl"] > 0).sum()
        losses = (today_df["pnl"] <= 0).sum()
        win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0

        logging.info(
            f"Daily PnL Summary | trades={total_trades} | wins={wins} | losses={losses} | win_rate={win_rate:.2f}% | pnl=${total_pnl:.4f}"
        )

    except Exception as e:
        logging.error(f"Daily PnL summary error: {repr(e)}")
        traceback.print_exc()

# ===== EXECUTION =====

def place_trade(exchange, symbol, side, amount):
    if side not in {"buy", "sell"}:
        raise ValueError(f"Unsupported paper order side: {side!r}")
    if not np.isfinite(amount) or amount <= 0:
        raise ValueError(f"Paper order amount must be positive and finite: {amount!r}")

    logging.info(f"[PAPER] {side.upper()} {symbol} amount={amount}")
    return {"paper": True, "side": side, "symbol": symbol, "amount": amount}

# ===== CORE LOOP =====
def is_bot_enabled():
    try:
        if not os.path.exists(CONTROL_FILE):
            print(f"[CONTROL] Missing bot control file: {CONTROL_FILE}", flush=True)
            return False

        with open(CONTROL_FILE, "r") as f:
            data = json.load(f)

        enabled = bool(data.get("bot_enabled", False))
        return enabled

    except Exception as e:
        print(f"[CONTROL ERROR] {e}", flush=True)
        return False

def apply_regime_flexibility(
    regime,
    macro_context,
    forecast,
    score,
    prob
):
    flexible_regime = dict(regime)

    regime_name = flexible_regime.get("regime", "unknown")
    macro_regime = macro_context.get("macro_regime", "macro_neutral")

    if regime_name == "crash_risk":
        return flexible_regime

    if macro_regime in ["macro_panic_event", "macro_bear_cycle"]:
        return flexible_regime

    if not macro_context.get("allow_new_longs", True):
        return flexible_regime

    if regime_name != "bear_trend":
        return flexible_regime

    panic_probability = forecast.get("panic_probability", 1.0)
    breakout_probability = forecast.get("breakout_probability", 0.0)
    expansion_probability = forecast.get("expansion_probability", 0.0)
    forecast_confidence = forecast.get("forecast_confidence", 0.0)

    transition_supported = (
        panic_probability < 0.70
        and (
            breakout_probability >= 0.20
            or expansion_probability >= 0.20
        )
        and forecast_confidence >= 0.30
    )

    signal_supported = (
        score >= 35
        and prob >= 0.25
    )

    if transition_supported and signal_supported:
        flexible_regime["regime"] = "defensive_bear_transition"
        flexible_regime["allow_long"] = True
        flexible_regime["risk_multiplier"] = max(
            0.15,
            min(float(flexible_regime.get("risk_multiplier", 0.0)) + 0.20, 0.35)
        )
        flexible_regime["reason"] = (
            flexible_regime.get("reason", "")
            + " | regime flexibility: defensive bear transition allowed with reduced risk"
        )

    return flexible_regime


def normalize_adaptive_thresholds(
    symbol,
    score_threshold,
    ai_threshold,
    regime,
    macro_context,
    global_sync,
    governance
):
    relief_reasons = []

    adjusted_score_threshold = score_threshold
    adjusted_ai_threshold = ai_threshold

    regime_name = regime.get("regime", "unknown")
    macro_regime = macro_context.get("macro_regime", "macro_neutral")
    sync_state = global_sync.get("market_state", "neutral")
    governance_rank = governance.get("final_rank", 0)

    score_relief = 0
    ai_relief = 0.0

    if regime_name == "sideways_chop":
        score_relief += 5
        ai_relief += 0.02
        relief_reasons.append("sideways chop threshold relief")

    if macro_regime == "macro_volatility_compression":
        score_relief += 4
        ai_relief += 0.02
        relief_reasons.append("macro compression threshold relief")

    if sync_state == "neutral":
        score_relief += 3
        ai_relief += 0.01
        relief_reasons.append("neutral synchronization threshold relief")

    if governance_rank >= 25:
        score_relief += 3
        ai_relief += 0.01
        relief_reasons.append("governance-supported opportunity relief")

    score_relief = min(score_relief, MAX_THRESHOLD_RELIEF)
    ai_relief = min(ai_relief, MAX_AI_THRESHOLD_RELIEF)

    if regime_name in ["bear_trend", "crash_risk"]:
        score_relief = 0
        ai_relief = 0.0
        relief_reasons = ["no relief allowed in bearish/crash regime"]

    if not macro_context.get("allow_new_longs", True):
        score_relief = 0
        ai_relief = 0.0
        relief_reasons = ["no relief allowed when macro blocks longs"]

    exceptional_relief = 0
    exceptional_ai_relief = 0.0

    if (
        regime_name == "sideways_chop"
        and macro_regime == "macro_volatility_compression"
        and sync_state in ["neutral", "global_risk_off"]
        and governance_rank >= 40
    ):
        exceptional_relief += 4
        exceptional_ai_relief += 0.01
        relief_reasons.append("selective opportunity relaxation")

    adjusted_score_threshold = max(
        30,
        adjusted_score_threshold - score_relief - exceptional_relief
    )

    adjusted_ai_threshold = max(
        0.20,
        adjusted_ai_threshold - ai_relief - exceptional_ai_relief
    )

    return {
        "symbol": symbol,
        "original_score_threshold": score_threshold,
        "original_ai_threshold": ai_threshold,
        "score_relief": score_relief,
        "ai_relief": ai_relief,
        "adjusted_score_threshold": adjusted_score_threshold,
        "adjusted_ai_threshold": adjusted_ai_threshold,
        "reason": " | ".join(relief_reasons) if relief_reasons else "thresholds unchanged"
    }


def normalize_execution_governance(
    symbol,
    raw_opportunity_rank,
    forecast,
    transition_signal,
    global_sync
):
    governance_reasons = []

    forecast_adjustment = 0

    if (
        forecast["next_regime"] == "breakout_expansion"
        and forecast["forecast_confidence"] >= FORECAST_CONFIDENCE_THRESHOLD
    ):
        forecast_adjustment = 8
        governance_reasons.append("forecast breakout expansion bonus")

    elif (
        forecast["next_regime"] == "trend_expansion"
        and forecast["forecast_confidence"] >= FORECAST_CONFIDENCE_THRESHOLD
    ):
        forecast_adjustment = 5
        governance_reasons.append("forecast trend expansion bonus")

    elif (
        forecast["next_regime"] == "panic_risk"
        and forecast["forecast_confidence"] >= FORECAST_CONFIDENCE_THRESHOLD
    ):
        panic_probability = forecast.get("panic_probability", 0.0)
        breakout_probability = forecast.get("breakout_probability", 0.0)
        expansion_probability = forecast.get("expansion_probability", 0.0)

        transitional_uncertainty = (
            panic_probability <= 0.85
            and (
                breakout_probability >= 0.10
                or expansion_probability >= 0.10
            )
        )

        if transitional_uncertainty:
            forecast_adjustment = -7
            governance_reasons.append(
                "forecast panic normalized as transitional uncertainty"
            )

        else:
            forecast_adjustment = -15
            governance_reasons.append("forecast panic risk penalty")

    elif (
        forecast["next_regime"] == "trend_exhaustion"
        and forecast["forecast_confidence"] >= FORECAST_CONFIDENCE_THRESHOLD
    ):
        forecast_adjustment = -8
        governance_reasons.append("forecast trend exhaustion penalty")

    transition_adjustment = transition_signal.get("rank_adjustment", 0)
    synchronization_adjustment = global_sync.get("rank_adjustment", 0)

    total_governance_adjustment = (
        forecast_adjustment +
        transition_adjustment +
        synchronization_adjustment
    )

    total_governance_adjustment = max(
        MAX_NEGATIVE_GOVERNANCE_IMPACT,
        total_governance_adjustment
    )

    final_rank = (
        raw_opportunity_rank +
        total_governance_adjustment
    )

    final_rank = max(0, min(final_rank, 100))

    final_rank = max(0, min(final_rank, 100))

    risk_governance_multiplier = (
        transition_signal.get("risk_adjustment", 1.00) *
        global_sync.get("risk_adjustment", 1.00)
    )

    risk_governance_multiplier = max(
        0.10,
        min(risk_governance_multiplier, 1.25)
    )

    if transition_adjustment != 0:
        governance_reasons.append(
            f"transition rank adjustment {transition_adjustment}"
        )

    if synchronization_adjustment != 0:
        governance_reasons.append(
            f"synchronization rank adjustment {synchronization_adjustment}"
        )

    if not governance_reasons:
        governance_reasons.append("governance neutral")

    return {
        "symbol": symbol,
        "raw_rank": raw_opportunity_rank,
        "forecast_adjustment": forecast_adjustment,
        "transition_adjustment": transition_adjustment,
        "synchronization_adjustment": synchronization_adjustment,
        "total_governance_adjustment": total_governance_adjustment,
        "final_rank": final_rank,
        "risk_governance_multiplier": risk_governance_multiplier,
        "reason": " | ".join(governance_reasons)
    }


def run():
    print("========== TRADE CYCLE STARTED ==========", flush=True)
    logging.info("========== TRADE CYCLE STARTED ==========")
    cycle_start_time = time.time()
    print("run() entered", flush=True)

    state = load_state()

    positions = state.get("positions", {})
    cash = state.get("cash", {})

    users = get_users()
    print("users loaded:", users)
    print("entering user loop")

    logging.info("Trading mode: PAPER (execution locked)")

    if not users:
        print("No users found in database.")
        return

    for user in users:
        username, enc_key, enc_secret, risk = user
        print("processing user:", username)

        try:
            # Public market data needs no customer exchange credentials.
            exchange = create_exchange("", "")
            print(f"{username}: exchange created")
            discovery_start = time.time()
            symbols = get_user_tradeable_symbols(username, exchange)
            print(
                f"DISCOVERY TIME = "
                f"{time.time() - discovery_start:.2f}s"
            )
            print(f"{username}: active Kraken trading universe = {symbols}")

            if not symbols:
                print(f"{username}: no symbols configured.")
                continue

            markets = exchange.load_markets()

            if username not in cash:
                cash[username] = PAPER_BALANCE_USD

            usd_balance = cash[username]

            print(f"{username}: usd_balance = {usd_balance}")

            if usd_balance <= 0:
                print(f"{username}: no free USD balance.")
                continue

            if username not in positions:
                positions[username] = {}

            for symbol in symbols:
                try:
                    if symbol not in markets:
                        print(f"{username}: unsupported symbol {symbol}")
                        continue
                    print(f"{username}: checking {symbol}")
                    mtf = fetch_multi_timeframe(exchange, symbol)

                    raw_df = mtf["main"]
                    higher_raw_df = mtf["higher"]
                    lower_raw_df = mtf["lower"]

                    df = indicators(raw_df)

                    if df.empty:
                        print(f"{symbol}: no usable indicator data, skipping.")
                        continue

                    price = float(df['close'].iloc[-1])

                    if len(df) < 30:
                        continue

                    score = strategy_score(df)
                    model = get_cached_model(symbol, df)
                    ai_model_available = model is not None

                    if not ai_model_available:
                        print(
                            f"{symbol}: AI model unavailable | "
                            f"blocking new entry until model is trainable"
                        )

                        raw_prob = 0.01
                        feature_importance = {}

                    else:
                        raw_prob = ai_prob(model, df)
                        feature_importance = log_feature_importance(symbol, model)


                    strat = load_strategy(df)
                    macro_context = detect_macro_market_context(exchange)

                    regime = detect_market_regime(df)

                    regime = apply_macro_to_regime(
                        regime,
                        macro_context
                    )


                    timeframe_alignment = detect_timeframe_alignment(
                        raw_df,
                        higher_raw_df,
                        lower_raw_df
                    )

                    if not ai_model_available:
                        fallback_prob = 0.01
                        alignment = timeframe_alignment.get("direction", "mixed")
                        regime_name = regime.get("regime", "unknown")
                        macro_regime = macro_context.get("macro_regime", "macro_neutral")


                        if score >= 90:
                            fallback_prob = 0.34
                        elif score >= 80:
                            fallback_prob = 0.30
                        elif score >= 70:
                            fallback_prob = 0.26
                        elif score >= 60:
                            fallback_prob = 0.22

                        if alignment == "strong_bullish":
                            fallback_prob += 0.06
                        elif alignment == "bullish":
                            fallback_prob += 0.04
                        elif alignment == "mixed":
                            fallback_prob -= 0.02

                        if regime_name == "bull_trend":
                            fallback_prob += 0.05
                        elif regime_name == "sideways_chop":
                            fallback_prob += 0.01
                        elif regime_name == "high_volatility":
                            fallback_prob -= 0.03
                        elif regime_name in ["bear_trend", "crash_risk"]:
                            fallback_prob = 0.01

                        if macro_regime in [
                            "macro_bull_expansion",
                            "macro_altseason_rotation",
                            "macro_accumulation",
                            "macro_volatility_compression"
                        ]:
                            fallback_prob += 0.03
                        elif macro_regime in [
                            "macro_distribution",
                            "macro_bear_cycle",
                            "macro_panic_event"
                        ]:
                            fallback_prob = 0.01

                        prob = max(0.01, min(fallback_prob, 0.42))


                    else:
                        prob = calibrate_ai_probability(
                            raw_prob,
                            df,
                            regime,
                            macro_context,
                            timeframe_alignment
                        )

                    print(
                        f"{symbol}: strategy score = {score}, "
                        f"raw AI probability = {raw_prob:.2f} | "
                        f"calibrated AI probability = {prob:.2f}"
                    )

                    print(
                        f"MACRO: regime={macro_context['macro_regime']} | "
                        f"risk_env={macro_context['risk_environment']} | "
                        f"market_heat={macro_context['market_heat']:.2f} | "
                        f"risk_mult={macro_context['risk_multiplier']:.2f} | "
                        f"capital_preservation={macro_context['capital_preservation']} | "
                        f"reason={macro_context['reason']}"
                    )

                    print(
                        f"{symbol}: market regime = {regime['regime']} | "
                        f"allow_long={regime['allow_long']} | "
                        f"risk_multiplier={regime['risk_multiplier']} | "
                        f"reason={regime['reason']}"
                    )

                    score += timeframe_alignment["score_bonus"]
                    feature_bias = get_regime_feature_bias(
                        symbol,
                        regime["regime"]
                    )
                    memory_score = get_market_memory_score(
                        symbol,
                        regime["regime"],
                        timeframe_alignment["direction"]
                    )

                    if ai_model_available:
                        score += memory_score


                    meta_bonus = 0

                    for feature_name, feature_score in feature_bias.items():
                        if feature_name in feature_importance:
                            meta_bonus += feature_score

                    meta_bonus = min(meta_bonus, 15)

                    if ai_model_available:
                        score += meta_bonus

                    score = max(0, min(score, 100))
                    prob = max(0, min(prob, 1))

                    if score > 95:
                        print(
                            f"{symbol}: score normalized | "
                            f"raw_score={score} -> capped_score=95"
                        )
                        score = 95

                    print(f"{symbol}: score={score}, prob={prob:.2f}, strat={strat}")
                    print(
                        f"{symbol}: timeframe alignment = "
                        f"{timeframe_alignment['direction']} | "
                        f"aligned={timeframe_alignment['aligned']} | "
                        f"score_bonus={timeframe_alignment['score_bonus']} | "
                        f"ai_bias_reference={timeframe_alignment['ai_bonus']:.2f}"
                    )

                    print(
                        f"{symbol}: market memory score = "
                        f"{memory_score}"
                    )

                    print(
                        f"{symbol}: meta learning bonus = "
                        f"{meta_bonus}"
                    )

                    opportunity_rank = calculate_opportunity_rank(
                        score,
                        prob,
                        regime,
                        macro_context,
                        timeframe_alignment,
                        memory_score
                    )

                    forecast = forecast_market_regime(
                        df,
                        macro_context,
                        regime
                    )

                    print(
                        f"{symbol}: regime forecast | "
                        f"next={forecast['next_regime']} | "
                        f"confidence={forecast['forecast_confidence']:.2f} | "
                        f"breakout={forecast['breakout_probability']:.2f} | "
                        f"expansion={forecast['expansion_probability']:.2f} | "
                        f"panic={forecast['panic_probability']:.2f} | "
                        f"exhaustion={forecast['exhaustion_probability']:.2f} | "
                        f"altseason={forecast['altseason_probability']:.2f}"
                    )

                    log_forecast_memory(
                        symbol,
                        macro_context,
                        regime,
                        forecast
                    )

                    transition_signal = get_forecast_transition_signal(symbol)

                    print(
                        f"{symbol}: forecast memory | "
                        f"state={transition_signal['transition_state']} | "
                        f"breakout={transition_signal['breakout_trend']} | "
                        f"expansion={transition_signal['expansion_trend']} | "
                        f"panic={transition_signal['panic_trend']} | "
                        f"exhaustion={transition_signal['exhaustion_trend']} | "
                        f"altseason={transition_signal['altseason_trend']} | "
                        f"rank_adj={transition_signal['rank_adjustment']} | "
                        f"risk_adj={transition_signal['risk_adjustment']:.2f} | "
                        f"reason={transition_signal['reason']}"
                    )

                    log_global_market_state(
                        symbol,
                        macro_context,
                        forecast,
                        transition_signal
                    )

                    global_sync = analyze_global_market_synchronization()

                    print(
                        f"{symbol}: global synchronization | "
                        f"market_state={global_sync['market_state']} | "
                        f"risk_mode={global_sync['risk_mode']} | "
                        f"sync_score={global_sync['synchronization_score']:.2f} | "
                        f"rank_adj={global_sync['rank_adjustment']} | "
                        f"risk_adj={global_sync['risk_adjustment']:.2f} | "
                        f"reason={global_sync['reason']}"
                    )
                    opportunity_rank += (
                        transition_signal["rank_adjustment"] +
                        global_sync["rank_adjustment"]
                    )


                    opportunity_rank = max(
                        0,
                        min(opportunity_rank, 100)
                    )


                    print(
                        f"{symbol}: raw opportunity rank = "
                        f"{opportunity_rank:.2f}"
                    )




                    user_positions = positions[username]
                    open_pos = user_positions.get(symbol)

                    if open_pos:
                        entry = float(open_pos["entry"])
                        amount = float(open_pos["amount"])

                        price = float(df["close"].iloc[-1])

                        adaptive_targets = get_adaptive_trade_targets(df, regime)

                        sl = entry * adaptive_targets["sl_multiplier"]

                        partial_tp = (
                            entry *
                            adaptive_targets["partial_tp_multiplier"]
                        )

                        trail_start = (
                            entry *
                            adaptive_targets["trail_start_multiplier"]
                        )

                        partial_taken = bool(open_pos.get("partial_taken", False))
                        peak = float(open_pos.get("peak", entry))

                        if price > peak:
                            peak = price
                            open_pos["peak"] = peak

                        trail_stop = (
                            peak *
                            (1 - adaptive_targets["trail_distance"])
                        )

                        print(f"{username}: HOLDING {symbol}")
                        print(
                            f"{symbol}: SL={sl:.6f} | partial TP={partial_tp:.6f} | "
                            f"trail start={trail_start:.6f} | peak={peak:.6f} | "
                            f"trail stop={trail_stop:.6f} | current={price:.6f}"
                        )

                        print(
                            f"{symbol}: adaptive exits | "
                            f"sl_mult={adaptive_targets['sl_multiplier']:.4f} | "
                            f"tp_mult={adaptive_targets['partial_tp_multiplier']:.4f} | "
                            f"trail_start={adaptive_targets['trail_start_multiplier']:.4f} | "
                            f"trail_distance={adaptive_targets['trail_distance']:.4f}"
                        )

                        open_pos["opportunity_rank"] = opportunity_rank
                        user_positions[symbol] = open_pos
                        positions[username] = user_positions
                        state["positions"] = positions
                        save_state(state)


                        if price <= sl:
                            print(f"{symbol}: STOP LOSS HIT")
                            pnl = (price - entry) * amount

                            log_market_memory(
                                symbol,
                                regime["regime"],
                                timeframe_alignment["direction"],
                                score,
                                prob,
                                pnl,
                                "LOSS"
                            )

                            log_feature_regime_memory(
                                symbol,
                                regime["regime"],
                                feature_importance,
                                pnl
                            )


                            log_trade_result(
                                username,
                                symbol,
                                entry,
                                price,
                                amount,
                                score,
                                prob,
                                "STOP_LOSS"
                            )

                            place_trade(exchange, symbol, "sell", amount)

                            set_symbol_cooldown(state, username, symbol)

                            sale_value = amount * price
                            cash_now = state["cash"].get(username, usd_balance)
                            state["cash"][username] = cash_now + sale_value
                            usd_balance = state["cash"][username]


                            del user_positions[symbol]
                            state["positions"][username] = user_positions
                            state["cash"][username] = usd_balance
                            save_state(state)
                            continue

                        if partial_taken is False and price >= partial_tp:
                            partial_amount = amount * PARTIAL_SELL_PERCENT
                            remaining_amount = amount - partial_amount

                            print(f"{symbol}: PARTIAL TAKE PROFIT HIT")
                            print(f"{symbol}: selling partial amount={partial_amount}")

                            log_trade_result(
                                username,
                                symbol,
                                entry,
                                price,
                                partial_amount,
                                score,
                                prob,
                                "PARTIAL_TAKE_PROFIT"
                            )

                            pnl = (price - entry) * partial_amount

                            log_market_memory(
                                symbol,
                                regime["regime"],
                                timeframe_alignment["direction"],
                                score,
                                prob,
                                pnl,
                                "WIN"
                            )

                            log_feature_regime_memory(
                                symbol,
                                regime["regime"],
                                feature_importance,
                                pnl
                            )

                            place_trade(exchange, symbol, "sell", partial_amount)
                            sale_value = partial_amount * price
                            state["cash"][username] = state.get("cash", {}).get(username, usd_balance) + sale_value
                            usd_balance = state["cash"][username]

                            open_pos["amount"] = remaining_amount
                            open_pos["partial_taken"] = True
                            open_pos["peak"] = price

                            user_positions[symbol] = open_pos
                            positions[username] = user_positions
                            state["positions"] = positions

                            save_state(state)

                            continue

                        if partial_taken:
                            if price <= trail_stop:
                                pnl = (price - entry) * amount

                                result = "WIN" if pnl > 0 else "LOSS"

                                log_market_memory(
                                    symbol,
                                    regime["regime"],
                                    timeframe_alignment["direction"],
                                    score,
                                    prob,
                                    pnl,
                                    result
                                )

                                log_feature_regime_memory(
                                    symbol,
                                    regime["regime"],
                                    feature_importance,
                                    pnl
                                )

                                print(f"{symbol}: TRAILING STOP HIT")
                                log_trade_result(
                                    username,
                                    symbol,
                                    entry,
                                    price,
                                    amount,
                                    score,
                                    prob,
                                    "TRAILING_STOP"
                                )

                                place_trade(exchange, symbol, "sell", amount)
                                sale_value = amount * price
                                cash_now = state["cash"].get(username, usd_balance)
                                state["cash"][username] = cash_now + sale_value
                                usd_balance = state["cash"][username]
                                del user_positions[symbol]
                                positions[username] = user_positions
                                state["positions"] = positions
                                save_state(state)

                                print(
                                    f"{symbol}: POSITION CLOSED | "
                                    f"cash=${state['cash'][username]:.2f} | "
                                    f"open_positions={len(user_positions)}"
                                )


                                continue

                        continue

                    if is_symbol_on_cooldown(state, username, symbol):
                        print(f"{symbol}: on cooldown after stop loss, skipping new entry.")
                        continue

                    history_conf = trade_history_confidence(symbol)
                    if history_conf is None:
                        history_conf = 0.0

                    performance = get_symbol_performance(symbol)

                    print(f"{symbol}: trade history confidence = {history_conf:.2f}")
                    print(
                        f"{symbol}: performance | trades={performance['trade_count']} | "
                        f"win_rate={performance['win_rate']:.2f} | "
                        f"avg_pnl={performance['avg_pnl']:.4f} | "
                        f"loss_streak={performance['loss_streak']} | "
                        f"cooldown_pressure={performance.get('cooldown_pressure', 0):.2f} | "
                        f"ai_threshold={performance['ai_threshold']:.2f} | "
                        f"score_threshold={performance['score_threshold']}"
                    )

                    if performance["paused"]:
                        reason = (
                            f"HARD PAUSED | "
                            f"loss_streak={performance['loss_streak']} | "
                            f"cooldown_pressure={performance['cooldown_pressure']:.2f}"
                        )

                        print(f"{symbol}: {reason}")

                        log_execution_journal(
                            username,
                            symbol,
                            "REJECTED",
                            reason,
                            score=score,
                            prob=prob,
                            opportunity_rank=opportunity_rank,
                            macro_regime=macro_context.get("macro_regime"),
                            regime=regime.get("regime"),
                            sync_state=global_sync.get("market_state"),
                            cash=usd_balance
                        )


                        continue

                    if performance.get("cooldown_pressure", 0) >= 0.60:
                        print(
                            f"{symbol}: adaptive cooldown active | "
                            f"loss_streak={performance['loss_streak']} | "
                            f"cooldown_pressure={performance['cooldown_pressure']:.2f} | "
                            f"thresholds tightened, trade still allowed if exceptional"
                        )

                    regime = apply_regime_flexibility(
                        regime,
                        macro_context,
                        forecast,
                        score,
                        prob
                    )

                    print(
                        f"{symbol}: regime flexibility | "
                        f"regime={regime['regime']} | "
                        f"allow_long={regime['allow_long']} | "
                        f"risk_multiplier={regime['risk_multiplier']} | "
                        f"reason={regime['reason']}"
                    )

                    if not regime["allow_long"]:
                        reason = (
                            f"blocked by market regime: "
                            f"{regime['regime']} - {regime['reason']}"
                        )

                        print(f"{symbol}: {reason}")

                        log_execution_journal(
                            username,
                            symbol,
                            "REJECTED",
                            reason,
                            score=score,
                            prob=prob,
                            opportunity_rank=opportunity_rank,
                            macro_regime=macro_context.get("macro_regime"),
                            regime=regime.get("regime"),
                            sync_state=global_sync.get("market_state"),
                            cash=usd_balance
                        )

                        continue

                    effective_score_threshold, effective_ai_threshold = get_dynamic_thresholds(
                        performance,
                        regime,
                        macro_context,
                        history_conf,
                        timeframe_alignment
                    )

                    print(
                        f"{symbol}: dynamic thresholds | "
                        f"score_required={effective_score_threshold} | "
                        f"ai_required={effective_ai_threshold:.2f}"
                    )

                    raw_opportunity_rank = calculate_opportunity_rank(
                        score,
                        prob,
                        regime,
                        macro_context,
                        timeframe_alignment,
                        memory_score,
                        history_conf,
                        performance.get("cooldown_pressure", 0.0)
                    )

                    governance = normalize_execution_governance(
                        symbol,
                        raw_opportunity_rank,
                        forecast,
                        transition_signal,
                        global_sync
                    )

                    opportunity_rank = governance["final_rank"]


                    print(
                        f"{symbol}: execution governance | "
                        f"raw_rank={governance['raw_rank']:.2f} | "
                        f"forecast_adj={governance['forecast_adjustment']} | "
                        f"transition_adj={governance['transition_adjustment']} | "
                        f"sync_adj={governance['synchronization_adjustment']} | "
                        f"total_adj={governance['total_governance_adjustment']} | "
                        f"final_rank={governance['final_rank']:.2f} | "
                        f"risk_mult={governance['risk_governance_multiplier']:.2f} | "
                        f"reason={governance['reason']}"
                    )

                    threshold_governance = normalize_adaptive_thresholds(
                        symbol,
                        effective_score_threshold,
                        effective_ai_threshold,
                        regime,
                        macro_context,
                        global_sync,
                        governance
                    )

                    effective_score_threshold = threshold_governance[
                        "adjusted_score_threshold"
                    ]

                    effective_ai_threshold = threshold_governance[
                        "adjusted_ai_threshold"
                    ]

                    print(
                        f"{symbol}: threshold governance | "
                        f"score_required={threshold_governance['original_score_threshold']} -> "
                        f"{threshold_governance['adjusted_score_threshold']} | "
                        f"ai_required={threshold_governance['original_ai_threshold']:.2f} -> "
                        f"{threshold_governance['adjusted_ai_threshold']:.2f} | "
                        f"score_relief={threshold_governance['score_relief']} | "
                        f"ai_relief={threshold_governance['ai_relief']:.2f} | "
                        f"reason={threshold_governance['reason']}"
                    )


                    print(
                        f"{symbol}: forecast-adjusted opportunity rank = "
                        f"{opportunity_rank:.2f}"
                    )

                    print(
                        f"{symbol}: FINAL EXECUTION GATE | "
                        f"score={score} vs required={effective_score_threshold} | "
                        f"prob={prob:.2f} vs required={effective_ai_threshold:.2f}"
                    )

                    log_execution_journal(
                        username,
                        symbol,
                        "EVALUATED",
                        "final execution gate evaluated",
                        score=score,
                        score_required=effective_score_threshold,
                        prob=prob,
                        prob_required=effective_ai_threshold,
                        opportunity_rank=opportunity_rank,
                        macro_regime=macro_context.get("macro_regime"),
                        regime=regime.get("regime"),
                        sync_state=global_sync.get("market_state"),
                        risk_multiplier=governance.get("risk_governance_multiplier"),
                        cash=usd_balance
                    )

                    explain_trade_decision(
                        symbol,
                        score,
                        prob,
                        history_conf,
                        performance,
                        regime,
                        effective_score_threshold,
                        effective_ai_threshold,
                        macro_context
                    )


                    if not (
                        score >= effective_score_threshold
                        and prob >= effective_ai_threshold
                        and history_conf >= 0.45
                        and macro_context["allow_new_longs"]
                    ):
                        reason = "execution conditions not met"


                        print(f"{symbol}: NO TRADE")


                        log_execution_journal(
                            username,
                            symbol,
                            "REJECTED",
                            reason,
                            score=score,
                            score_required=effective_score_threshold,
                            prob=prob,
                            prob_required=effective_ai_threshold,
                            opportunity_rank=opportunity_rank,
                            macro_regime=macro_context.get("macro_regime"),
                            regime=regime.get("regime"),
                            sync_state=global_sync.get("market_state"),
                            risk_multiplier=governance.get("risk_governance_multiplier"),
                            cash=usd_balance
                        )


                        continue

                    has_duplicate_base, duplicate_symbol = has_existing_base_asset_exposure(
                        symbol,
                        user_positions
                    )

                    if has_duplicate_base:
                        print(
                            f"{symbol}: duplicate exposure blocked | "
                            f"already holding {duplicate_symbol}"
                        )
                        continue


                    dynamic_risk_multiplier = calculate_dynamic_risk_multiplier(
                        score,
                        prob,
                        history_conf,
                        regime,
                        memory_score,
                        timeframe_alignment
                    )

                    adjusted_risk = (
                        risk *
                        regime["risk_multiplier"] *
                        dynamic_risk_multiplier *
                        macro_context["altcoin_aggression"] *
                        governance["risk_governance_multiplier"]
                    )

                    print(
                        f"{symbol}: dynamic risk | "
                        f"base_risk={risk:.4f} | "
                        f"regime_mult={regime['risk_multiplier']:.2f} | "
                        f"dynamic_mult={dynamic_risk_multiplier:.2f} | "
                        f"macro_alt_mult={macro_context['altcoin_aggression']:.2f} | "
                        f"transition_risk_mult={transition_signal['risk_adjustment']:.2f} | "
                        f"global_risk_mult={global_sync['risk_adjustment']:.2f} | "
                        f"final_risk={adjusted_risk:.4f}"
                    )

                    sector_context = evaluate_sector_allocation(
                        symbol,
                        user_positions,
                        opportunity_rank
                    )

                    print(
                        f"{symbol}: sector intelligence | "
                        f"sector={sector_context['sector']} | "
                        f"sector_count={sector_context['sector_count']} | "
                        f"correlation_risk={sector_context['correlation_risk']:.2f} | "
                        f"allowed={sector_context['allow_sector_entry']} | "
                        f"reason={sector_context['reason']}"
                    )

                    if not sector_context["allow_sector_entry"]:
                        print(
                            f"{symbol}: sector/correlation block | "
                            f"{sector_context['reason']}"
                        )
                        continue

                    max_open_positions = get_user_max_open_positions(username)

                    if len(user_positions) >= max_open_positions:

                        weakest_symbol, weakest_rank = find_weakest_open_position(
                                user_positions
                        )

                        print(
                            f"{symbol}: portfolio full | "
                            f"positions={len(user_positions)}/{max_open_positions} | "
                            f"candidate_rank={opportunity_rank:.2f} | "
                            f"weakest_position={weakest_symbol} | "
                            f"weakest_rank={weakest_rank:.2f}"
                        )

                        if not should_rotate_capital(
                            opportunity_rank,
                            weakest_rank
                        ):
                            print(
                                f"{symbol}: no rotation | "
                                f"candidate does not beat weakest position enough"
                            )
                            continue

                        weakest_position = user_positions.get(weakest_symbol)

                        if weakest_position is None:
                            print(
                                f"{symbol}: rotation blocked | "
                                f"weakest position not found"
                            )
                            continue


                        weakest_amount = float(
                            weakest_position["amount"]
                        )

                        weakest_price = get_latest_symbol_price(
                            exchange,
                            weakest_symbol
                        )


                        if weakest_price is None:
                            print(
                                f"{symbol}: rotation blocked | "
                                f"could not price weakest position"
                            )
                            continue


                        weakest_entry = float(
                            weakest_position["entry"]
                        )

                        weakest_pnl_percent = (
                            (weakest_price - weakest_entry) /
                            weakest_entry
                        )

                        weakest_partial_taken = bool(
                            weakest_position.get("partial_taken", False)
                        )

                        if (
                            weakest_pnl_percent > 0
                            or weakest_partial_taken
                        ):
                            print(
                                f"{symbol}: rotation blocked | "
                                f"{weakest_symbol} protected | "
                                f"pnl={weakest_pnl_percent:.2%} | "
                                f"partial_taken={weakest_partial_taken}"
                            )
                            continue


                        print(
                            f"{symbol}: ROTATING CAPITAL | "
                            f"selling {weakest_symbol} to fund stronger setup"
                        )

                        place_trade(
                            exchange,
                            weakest_symbol,
                            "sell",
                            weakest_amount
                        )

                        sale_value = weakest_amount * weakest_price


                        cash_now = state["cash"].get(
                            username,
                            usd_balance
                        )

                        state["cash"][username] = (
                            cash_now + sale_value
                        )

                        usd_balance = state["cash"][username]


                        del user_positions[weakest_symbol]


                        positions[username] = user_positions
                        state["positions"] = positions


                        save_state(state)


                    amount = calculate_position_size(
                        usd_balance,
                        adjusted_risk,
                        price
                    )

                    if amount <= 0:
                        print(
                            f"{symbol}: position size invalid, skipping trade."
                        )
                        continue


                    estimated_cost = amount * price


                    if estimated_cost > usd_balance:
                        print(
                            f"{symbol}: not enough USD balance for trade."
                        )
                        continue


                    log_execution_journal(
                        username,
                        symbol,
                        "ACCEPTED",
                        "entry confirmed",
                        score=score,
                        score_required=effective_score_threshold,
                        prob=prob,
                        prob_required=effective_ai_threshold,
                        opportunity_rank=opportunity_rank,
                        macro_regime=macro_context.get("macro_regime"),
                        regime=regime.get("regime"),
                        sync_state=global_sync.get("market_state"),
                        risk_multiplier=governance.get("risk_governance_multiplier"),
                        cash=usd_balance
                    )


                    print(f"{symbol}: ENTRY CONFIRMED")


                    print(
                        f"{symbol}: calculated amount = "
                        f"{amount} | estimated cost = ${estimated_cost:.2f}"
                    )

                    buy_order = place_trade(exchange, symbol, "buy", amount)


                    if buy_order is None:
                        print(
                            f"{symbol}: BUY FAILED | "
                            f"position not opened and cash not changed"
                        )
                        continue


                    print(
                        f"{symbol}: BUY EXECUTED | "
                        f"order={buy_order}"
                    )

                    cost = amount * price
                    state["cash"][username] = usd_balance - cost


                    usd_balance = state["cash"][username]


                    user_positions[symbol] = {
                        "entry": price,
                        "amount": amount,
                        "partial_taken": False,
                        "peak": price,
                        "opportunity_rank": opportunity_rank,
                        "sector": get_symbol_sector(symbol)
                    }

                    positions[username] = user_positions
                    state["positions"] = positions


                    save_state(state)

                    print(
                        f"{symbol}: POSITION SAVED | "
                        f"cash=${state['cash'][username]:.2f} | "
                        f"open_positions={len(user_positions)}"
                    )


                except Exception as symbol_error:
                    logging.error("========== SYMBOL ERROR ==========")
                    logging.error(f"{username} {symbol}: {repr(symbol_error)}")
                    traceback.print_exc()

            cash = state["cash"].get(username, usd_balance)
            starting_balance = PAPER_START_BALANCE
            position_value = 0
            total_pnl = 0
            open_count = 0

            for pos_symbol, pos in positions.get(username, {}).items():
                entry = float(pos["entry"])
                amount = float (pos["amount"])

                try:
                    ticker = exchange.fetch_ticker(pos_symbol)
                    current = float(ticker["last"])
                except Exception:
                    current = entry

                value = current * amount
                pnl = (current - entry) * amount

                position_value += value
                total_pnl += pnl
                open_count += 1

            equity = cash + position_value
            pnl = equity - starting_balance
            pct = (pnl / starting_balance) * 100

            print(
                f"{username}: SUMMARY | cash=${cash:.2f} | "
                f"position_value=${position_value:.2f} | "
                f"equity=${equity:.2f} | "
                f"pnl=${pnl:.2f} ({pct:.2f}%) | "
                f"open_positions={open_count}"
            )

            print(
                f"FULL CYCLE TIME = "
                f"{time.time() - cycle_start_time:.2f}s"
            )
            print("========== TRADE CYCLE FINISHED ==========", flush=True)
            logging.info("========== TRADE CYCLE FINISHED ==========")

            save_dashboard_status(
                username,
                cash,
                position_value,
                equity,
                pnl,
                pct,
                open_count,
                positions
            )


        except Exception as user_error:
            logging.error(f"{username} user-level error: {repr(user_error)}")
            traceback.print_exc()

# ===== NEXORA BACKEND CONTRACT =====
# These functions are the single runtime contract used by the FastAPI backend,
# dashboard endpoints, supervisor, restart recovery, and reliability tests.
BACKEND_BASE_DIR = os.path.abspath(
    os.environ.get("NEXORA_BACKEND_DIR", "/home/marty/backend")
)
BOTS_FILE = os.path.join(BACKEND_BASE_DIR, "bots.json")
POSITIONS_FILE = os.path.join(BACKEND_BASE_DIR, "asset_bot_positions.json")
TRADES_FILE = os.path.join(BACKEND_BASE_DIR, "asset_bot_trades.json")
LOGS_FILE = os.path.join(BACKEND_BASE_DIR, "asset_bot_logs.json")
MANUAL_CLOSE_GUARD = threading.Lock()


def _backend_store():
    from app.core.json_store import load_json, save_json, update_json
    return load_json, save_json, update_json


def log_event(message, level="INFO"):
    _, _, update_json = _backend_store()

    def append_log(logs):
        logs.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": "bot3_backup",
            "message": str(message),
        })
        return logs[-500:]

    update_json(LOGS_FILE, [], append_log)


def get_enabled_asset_bots(username=None):
    load_json, _, _ = _backend_store()
    bots = load_json(BOTS_FILE, {})
    enabled = []
    for bot_username, user_bots in bots.items():
        if username and bot_username != username:
            continue
        for bot in user_bots:
            if bot.get("bot_type") != "asset_specific":
                continue
            if bot.get("enabled") is False or bot.get("mode", "paper") != "paper":
                continue
            enabled.append({"username": bot_username, **bot})
    return enabled


def update_bot_runtime_status(username, bot_id, current_open_positions, last_action):
    _, _, update_json = _backend_store()
    updated = False

    def mutate(bots):
        nonlocal updated
        for bot in bots.get(username, []):
            if bot.get("id") == bot_id:
                bot["current_open_positions"] = current_open_positions
                bot["last_action"] = last_action
                bot["last_scan"] = datetime.now(timezone.utc).isoformat()
                updated = True
                break
        return bots

    update_json(BOTS_FILE, {}, mutate)
    return updated


def fetch_price(symbol, attempts=3, base_delay_seconds=0.5):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            exchange = ccxt.kraken({"enableRateLimit": True, "timeout": 10000})
            ticker = exchange.fetch_ticker(symbol)
            price = ticker.get("last") or ticker.get("close")
            if price is None or not np.isfinite(float(price)) or float(price) <= 0:
                raise ValueError(f"No valid market price returned for {symbol}")
            try:
                from app.reliability import record_kraken_success
                record_kraken_success()
            except ImportError:
                pass
            return float(price)
        except Exception as error:
            last_error = error
            try:
                from app.reliability import record_kraken_failure
                record_kraken_failure(error)
            except ImportError:
                pass
            log_event(
                f"Kraken price request failed for {symbol} "
                f"(attempt {attempt}/{attempts}): {type(error).__name__}",
                "WARNING",
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
    load_json, _, _ = _backend_store()
    return load_json(POSITIONS_FILE, {})


def save_positions(positions):
    _, save_json, _ = _backend_store()
    save_json(POSITIONS_FILE, positions)


def get_existing_position(username, bot_id):
    return load_positions().get(get_position_key(username, bot_id))


def save_position(username, bot_id, position):
    _, _, update_json = _backend_store()
    key = get_position_key(username, bot_id)
    update_json(POSITIONS_FILE, {}, lambda positions: {**positions, key: position})


def remove_position(username, bot_id):
    _, _, update_json = _backend_store()
    key = get_position_key(username, bot_id)
    removed = False

    def mutate(positions):
        nonlocal removed
        removed = positions.pop(key, None) is not None
        return positions

    update_json(POSITIONS_FILE, {}, mutate)
    return removed


def analyze_backend_bot(bot):
    """Produce an auditable, fail-closed paper-entry decision."""
    symbol = bot["symbol"]
    try:
        exchange = ccxt.kraken({"enableRateLimit": True, "timeout": 15000})
        mtf = fetch_multi_timeframe(exchange, symbol)
        df = indicators(mtf["main"])
        if df.empty or len(df) < 60:
            raise ValueError("insufficient feature-complete market history")

        score = float(strategy_score(df))
        historical_raw = load_training_history(exchange, symbol)
        historical_features = indicators(historical_raw)
        model = get_cached_model(symbol, historical_features)
        alignment = detect_timeframe_alignment(
            mtf["main"], mtf["higher"], mtf["lower"]
        )
        macro = detect_macro_market_context(exchange)
        regime = apply_macro_to_regime(detect_market_regime(df), macro)

        if model is None:
            probability = 0.0
            model_status = "rejected_by_validation"
            disagreement = 1.0
            drift_z = float("inf")
        else:
            probability = calibrate_ai_probability(
                ai_prob(model, df), df, regime, macro, alignment
            )
            model_status = "validated"
            disagreement = model.disagreement(df.tail(50))
            drift_z = model.drift_z(df.tail(50))

        external = load_external_feature_snapshot(
            symbol,
            float(df["time"].iloc[-1]),
        )
        uncertainty_reasons = []
        if disagreement > MAX_MODEL_DISAGREEMENT:
            uncertainty_reasons.append("specialist disagreement")
        if drift_z > MAX_FEATURE_DRIFT_Z:
            uncertainty_reasons.append("feature distribution drift")
        if model is not None and model.validation_metrics.get("ece", 1.0) > MAX_CALIBRATION_ECE:
            uncertainty_reasons.append("calibration deterioration")
        if external.get("required") and not external.get("available"):
            uncertainty_reasons.append("required external context missing or stale")
        calibration_error = (
            float(model.validation_metrics.get("ece", 1.0)) if model is not None else 1.0
        )
        quarantined = record_drift_observation(
            symbol, disagreement, drift_z, calibration_error
        )
        if quarantined:
            uncertainty_reasons.append("model health quarantine")

        score += float(alignment.get("score_bonus", 0))
        required_score = float(bot.get("min_score", BASE_SCORE_THRESHOLD) or BASE_SCORE_THRESHOLD)
        required_probability = float(
            bot.get("min_ai_probability", AI_THRESHOLD) or AI_THRESHOLD
        )
        allowed = bool(
            model is not None
            and regime.get("allow_long", False)
            and macro.get("allow_new_longs", False)
            and score >= required_score
            and probability >= required_probability
            and not uncertainty_reasons
        )

        return {
            "allowed": allowed,
            "score": round(score, 4),
            "required_score": required_score,
            "probability": round(float(probability), 6),
            "required_probability": required_probability,
            "model_status": model_status,
            "model_disagreement": round(float(disagreement), 6),
            "feature_drift_z": round(float(drift_z), 6) if np.isfinite(drift_z) else None,
            "abstention_reasons": uncertainty_reasons,
            "quarantined": quarantined,
            "external_features": external,
            "history_rows": len(historical_features),
            "history_start": int(historical_raw["time"].iloc[0]),
            "history_end": int(historical_raw["time"].iloc[-1]),
            "regime": regime.get("regime", "unknown"),
            "macro_regime": macro.get("macro_regime", "macro_neutral"),
            "timeframe_alignment": alignment.get("direction", "mixed"),
            "reason": (
                "entry gates passed"
                if allowed
                else " | ".join(uncertainty_reasons) or "entry gates not satisfied"
            ),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as error:
        return {
            "allowed": False,
            "model_status": "analysis_error",
            "reason": f"{type(error).__name__}: {error}",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }


def open_paper_position(bot, price, intelligence=None):
    username, bot_id = bot["username"], bot["id"]
    allocated_cash = float(bot.get("allocated_cash", 0) or 0)
    if allocated_cash <= 0 or price <= 0:
        raise ValueError("Cannot open position without valid allocated cash and price")

    position = {
        "username": username,
        "bot_id": bot_id,
        "bot_name": bot.get("name", "Asset Bot"),
        "symbol": bot["symbol"],
        "entry_price": float(price),
        "amount": allocated_cash / float(price),
        "allocated_cash": allocated_cash,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "peak_price": float(price),
        "status": "open",
        "intelligence": intelligence or {"source": "controlled_test"},
    }
    _, _, update_json = _backend_store()
    key = get_position_key(username, bot_id)
    created = False

    def create_if_missing(positions):
        nonlocal created, position
        if key in positions:
            position = positions[key]
        else:
            positions[key] = position
            created = True
        return positions

    update_json(POSITIONS_FILE, {}, create_if_missing)
    if created:
        update_bot_runtime_status(username, bot_id, 1, "AI-approved paper position opened")
        log_event(f"Opened AI-approved paper position for {username}/{bot_id}")
    else:
        log_event(f"Duplicate open prevented for {username}/{bot_id}", "WARNING")
    return position


def close_paper_position(position, exit_price, reason):
    entry = float(position.get("entry_price", 0) or 0)
    amount = float(position.get("amount", 0) or 0)
    if entry <= 0 or amount <= 0 or exit_price <= 0:
        raise ValueError("Invalid position cannot be closed")
    pnl = (float(exit_price) - entry) * amount
    trade = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "username": position["username"],
        "bot_id": position["bot_id"],
        "bot_name": position.get("bot_name", "Asset Bot"),
        "symbol": position["symbol"],
        "entry_price": entry,
        "exit_price": float(exit_price),
        "amount": amount,
        "entry_value": entry * amount,
        "exit_value": float(exit_price) * amount,
        "pnl": pnl,
        "pnl_percent": ((float(exit_price) - entry) / entry) * 100,
        "reason": reason,
        "opened_at": position.get("opened_at"),
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "intelligence": position.get("intelligence", {}),
    }
    _, _, update_json = _backend_store()
    update_json(TRADES_FILE, [], lambda trades: (trades + [trade])[-1000:])
    remove_position(position["username"], position["bot_id"])
    update_bot_runtime_status(position["username"], position["bot_id"], 0, f"Closed ({reason})")
    log_event(f"Closed {position['symbol']} for {position['username']}: {reason}")
    return trade


def close_existing_paper_position(username, bot_id):
    """Atomically close one paper position without waiting for an AI exit."""
    with MANUAL_CLOSE_GUARD:
        position = get_existing_position(username, bot_id)
        if not position:
            return None
        return close_paper_position(
            position,
            fetch_price(position["symbol"]),
            "MANUAL_CLOSE",
        )


def update_open_position(position, current_price):
    entry = float(position.get("entry_price", 0) or 0)
    amount = float(position.get("amount", 0) or 0)
    if entry <= 0 or amount <= 0 or current_price <= 0:
        raise ValueError("Invalid open position")
    peak = max(float(position.get("peak_price", entry) or entry), float(current_price))
    position.update({
        "current_price": float(current_price),
        "current_value": amount * float(current_price),
        "unrealized_pnl": (float(current_price) - entry) * amount,
        "unrealized_pnl_percent": ((float(current_price) - entry) / entry) * 100,
        "peak_price": peak,
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
    })
    return position


def scan_asset_bot(bot):
    symbol, username, bot_id = bot.get("symbol"), bot.get("username"), bot.get("id")
    if not symbol or not username or not bot_id:
        raise ValueError("Bot is missing username, id, or symbol")
    if bot.get("mode", "paper") != "paper":
        raise ValueError("Unified bot3 runtime accepts paper bots only")

    existing = get_existing_position(username, bot_id)
    price = fetch_price(symbol)
    if not existing:
        intelligence = analyze_backend_bot(bot)
        if not intelligence.get("allowed"):
            update_bot_runtime_status(username, bot_id, 0, "AI entry rejected")
            log_event(
                f"Entry rejected for {username}/{bot_id}: {intelligence.get('reason')}",
                "INFO",
            )
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "username": username,
                "bot_id": bot_id,
                "symbol": symbol,
                "price": price,
                "status": "entry_rejected",
                "intelligence": intelligence,
            }
        position = open_paper_position(bot, price, intelligence)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "username": username,
            "bot_id": bot_id,
            "symbol": symbol,
            "price": price,
            "status": "opened_paper_position",
            "position": position,
        }

    position = update_open_position(existing, price)
    pnl_percent = position["unrealized_pnl_percent"]
    take_profit = float(bot.get("take_profit_percent", 5.0) or 5.0)
    stop_loss = float(bot.get("stop_loss_percent", 2.0) or 2.0)
    trailing = float(bot.get("trailing_stop_percent", 1.5) or 1.5)
    peak = float(position.get("peak_price", price) or price)
    peak_drawdown = ((price - peak) / peak) * 100 if peak > 0 else 0

    reason = status = None
    if pnl_percent <= -stop_loss:
        reason, status = f"STOP_LOSS_{stop_loss:.2f}_PERCENT", "closed_stop_loss"
    elif pnl_percent >= take_profit:
        reason, status = f"TAKE_PROFIT_{take_profit:.2f}_PERCENT", "closed_take_profit"
    elif peak > float(position["entry_price"]) and peak_drawdown <= -trailing:
        reason, status = f"TRAILING_STOP_{trailing:.2f}_PERCENT", "closed_trailing_stop"

    if reason:
        trade = close_paper_position(position, price, reason)
        return {"bot_id": bot_id, "symbol": symbol, "status": status, "trade": trade}

    save_position(username, bot_id, position)
    update_bot_runtime_status(username, bot_id, 1, "AI position monitoring")
    return {"bot_id": bot_id, "symbol": symbol, "status": "position_updated", "position": position}


def scan_all_enabled_bots(username=None):
    enabled = get_enabled_asset_bots(username)
    results = []

    def isolated(bot):
        try:
            return scan_asset_bot(bot)
        except Exception as error:
            log_event(
                f"Bot scan failed for {bot.get('symbol', 'UNKNOWN')}: "
                f"{type(error).__name__}: {error}",
                "ERROR",
            )
            return None

    if enabled:
        with ThreadPoolExecutor(max_workers=min(10, len(enabled)), thread_name_prefix="bot3") as executor:
            futures = [executor.submit(isolated, bot) for bot in enabled]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)

    try:
        from app.reliability import update_health
        update_health(
            active_bots=len(enabled),
            open_positions=len(load_positions()),
            last_engine_cycle=datetime.now(timezone.utc).isoformat(),
            last_engine_error=None,
        )
    except ImportError:
        pass
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(results),
        "results": results,
    }


# ===== MAIN =====
if __name__ == "__main__":
    print(json.dumps(scan_all_enabled_bots(), indent=2))
