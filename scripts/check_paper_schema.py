"""Check Nexora schema migration readiness without creating tables."""
from sqlalchemy import inspect
from app.core.database import engine

EXPECTED = {
    "users",
    "strategies",
    "nexora_paper_wallets",
    "nexora_desktop_paper_bots",
}


def main():
    print("Database dialect:", engine.dialect.name)
    print("Database name:", engine.url.database or "(none)")
    print("Database host:", engine.url.host or "(local)")
    print("No schema changes will be made.")
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    for table in sorted(EXPECTED):
        print(f"{table}: {'present' if table in existing else 'missing'}")
    if "users" not in existing or "strategies" not in existing:
        raise SystemExit("Blocked: required existing users/strategies tables are missing.")


if __name__ == "__main__":
    main()
