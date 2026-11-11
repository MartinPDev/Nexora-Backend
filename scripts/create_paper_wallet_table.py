"""Create a separate Nexora paper-wallet table before enabling wallet routes.

This migration does not access or modify Sniper Bot data or real exchange balances.
"""
import os
from sqlalchemy import inspect
from app.core.database import engine
from app.models.paper_wallet import PaperWallet


def main():
    if os.getenv("NEXORA_CONFIRM_SCHEMA_CREATE") != "YES":
        raise SystemExit(
            "Schema creation blocked. Inspect DATABASE_URL and set "
            "NEXORA_CONFIRM_SCHEMA_CREATE=YES explicitly to proceed."
        )
    if engine.url.database is None:
        raise SystemExit("Schema creation blocked: database name is missing.")
    if inspect(engine).has_table(PaperWallet.__tablename__):
        print("Nexora paper-wallet table already exists; no changes made.")
        return
    PaperWallet.__table__.create(bind=engine, checkfirst=True)
    print("Created Nexora paper-wallet table. No user wallets were funded.")


if __name__ == "__main__":
    main()
