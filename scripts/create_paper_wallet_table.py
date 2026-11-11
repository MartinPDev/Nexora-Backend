"""Create a separate Nexora paper-wallet table before enabling wallet routes.

This migration does not access or modify Sniper Bot data or real exchange balances.
"""
from sqlalchemy import inspect
from app.core.database import engine
from app.models.paper_wallet import PaperWallet


def main():
    if inspect(engine).has_table(PaperWallet.__tablename__):
        print("Nexora paper-wallet table already exists; no changes made.")
        return
    PaperWallet.__table__.create(bind=engine, checkfirst=True)
    print("Created Nexora paper-wallet table. No user wallets were funded.")


if __name__ == "__main__":
    main()
