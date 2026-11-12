"""Read-only preflight for the isolated local Nexora paper-preview schema.

Usage (after configuring local backend environment):
    python -m scripts.check_preview_schema
Never applies migrations, creates accounts, or starts trading.
"""
import os
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from app.core.config import get_settings
from app.core.database import engine

REQUIRED = {
    "nexora_preview_enrollments": {
        "bot_id", "user_id", "observer_enabled", "last_action", "last_reason",
        "last_scanned_at", "created_at",
    },
    "nexora_preview_proposals": {
        "id", "user_id", "bot_id", "symbol", "candle_timestamp",
        "price", "quantity", "principal", "fee", "payload_hash",
        "status", "created_at", "expires_at",
    },
    "nexora_preview_positions": {
        "id", "user_id", "bot_id", "proposal_id", "symbol",
        "entry_price", "quantity", "principal", "entry_fee", "peak_price",
        "status", "opened_at", "closed_at", "exit_price", "exit_fee",
        "pnl", "exit_reason",
    },
}


def check():
    settings = get_settings()
    url = make_url(settings.database_url)
    if (os.getenv("NEXORA_LOCAL_DESKTOP_API") != "YES"
            or url.database != "cryptobot"
            or url.host not in {"localhost", "127.0.0.1"}
            or settings.app_env.lower() in {"prod", "production"}):
        raise RuntimeError("Preview preflight only permits explicitly enabled local cryptobot.")
    inspector = inspect(engine)
    missing = {}
    for table, columns in REQUIRED.items():
        if not inspector.has_table(table):
            missing[table] = sorted(columns)
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        if columns - present:
            missing[table] = sorted(columns - present)
    if missing:
        raise RuntimeError("Preview schema is incomplete: " + repr(missing))
    indexes = inspector.get_indexes("nexora_preview_positions")
    if not any(index["name"] == "uq_preview_open_bot" and index.get("unique") for index in indexes):
        raise RuntimeError("Missing unique-open-position safety index.")
    print("PASS: Local preview schema and single-open-position index present. No data changed.")


if __name__ == "__main__":
    check()
