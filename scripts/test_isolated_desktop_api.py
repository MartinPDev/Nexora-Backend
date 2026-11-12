"""Isolated Nexora API integration harness; no app.main or trading workers.

Runs only with NEXORA_RUN_INTEGRATION=YES and creates one clearly labelled
test account in the configured database. No cleanup is performed automatically.
"""
import os
import secrets
import uuid
from decimal import Decimal

if os.getenv("NEXORA_RUN_INTEGRATION") != "YES":
    raise SystemExit("Blocked: set NEXORA_RUN_INTEGRATION=YES explicitly.")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from app.core.config import get_settings
from app.api.routes import auth, strategies, desktop

settings = get_settings()
url = make_url(settings.database_url)
if url.database != "cryptobot":
    raise SystemExit("Blocked: expected cryptobot database.")
if url.host not in {"localhost", "127.0.0.1"}:
    raise SystemExit("Blocked: integration test requires local database.")

engine = create_engine(settings.database_url, connect_args={"connect_timeout": 5})
with engine.connect() as connection:
    dbname = connection.execute(text("SELECT current_database()")).scalar_one()
    if dbname != "cryptobot":
        raise SystemExit("Blocked: connected to unexpected database.")

app = FastAPI()
app.include_router(auth.router, prefix="/api/v1")
app.include_router(strategies.router, prefix="/api/v1")
app.include_router(desktop.router, prefix="/api/v1")

suffix = uuid.uuid4().hex[:12]
username = "nexora_it_" + suffix
email = username + "@example.com"
password = secrets.token_urlsafe(32)
client = TestClient(app)

def request(method, path, *, expected, **kwargs):
    response = client.request(method, "/api/v1" + path, **kwargs)
    if response.status_code != expected:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:400]}")
    return response.json()

print("Registering dedicated integration account:", username)
account = request("POST", "/auth/register", expected=200, json={
    "username": username, "email": email, "password": password,
})
login = request("POST", "/auth/login", expected=200, json={
    "username_or_email": username, "password": password,
})
headers = {"Authorization": "Bearer " + login["access_token"]}
# Authorization must reject unauthenticated requests, without creating other accounts.
request("GET", "/desktop/bots", expected=401)
request("GET", "/desktop/portfolio", expected=401)
request("GET", "/desktop/trades", expected=401)
request("POST", "/desktop/bots", expected=401, json={
    "name": "Unauthorized", "symbol": "BTC/USD", "timeframe": "15m",
    "strategy_id": str(uuid.uuid4()), "allocated_cash": 100, "risk_percent": 1,
})
wallet = request("GET", "/desktop/portfolio", expected=200, headers=headers)
assert wallet["cash"] == 1000.0 and wallet["financial_data_status"] == "cash_and_reservations_only"
repeat = request("GET", "/desktop/portfolio", expected=200, headers=headers)
assert repeat["cash"] == 1000.0

strategy = request("POST", "/strategies", expected=200, headers=headers, json={
    "name": "Integration Paper BTC", "symbol": "BTC/USD", "timeframe": "15m",
    "risk_percent": 1, "take_profit_percent": 4, "stop_loss_percent": 2,
    "is_ai_enabled": True, "config_json": {"paper_only": True, "mode": "balanced"},
})
bot = request("POST", "/desktop/bots", expected=201, headers=headers, json={
    "name": "Integration Paper Bot", "symbol": "BTC/USD", "timeframe": "15m",
    "strategy_id": strategy["id"], "allocated_cash": 600, "risk_percent": 1,
})
assert bot["is_enabled"] is False and bot["mode"] == "paper"
after_allocation = request("GET", "/desktop/portfolio", expected=200, headers=headers)
assert after_allocation["cash"] == 400.0
assert after_allocation["reserved_cash"] == 600.0
assert after_allocation["paper_cash_balance"] == 1000.0
assert after_allocation["total_value"] is None
request("POST", "/desktop/bots", expected=409, headers=headers, json={
    "name": "Overallocated", "symbol": "BTC/USD", "timeframe": "15m",
    "strategy_id": strategy["id"], "allocated_cash": 500, "risk_percent": 1,
})
bots = request("GET", "/desktop/bots", expected=200, headers=headers)
assert len(bots["bots"]) == 1
summary = request("GET", "/desktop/dashboard", expected=200, headers=headers)
assert summary["bots_total"] == 1 and summary["bots_running"] == 0
print("PASS: registration, login, $1000 wallet, strategy, inactive bot, allocation rejection")
print("Test account retained for audit:", username)
print("No trading workers or exchange connections started.")
