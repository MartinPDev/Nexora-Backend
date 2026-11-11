"""Explicit schema creation for isolated Nexora desktop paper bots."""
import os
from sqlalchemy import inspect, create_engine
from app.core.config import get_settings
from app.models.desktop_paper_bot import DesktopPaperBot


def main():
    if os.getenv("NEXORA_CONFIRM_SCHEMA_CREATE") != "YES":
        raise SystemExit(
            "Schema creation blocked. Inspect DATABASE_URL and set "
            "NEXORA_CONFIRM_SCHEMA_CREATE=YES explicitly to proceed."
        )
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        connect_args={"connect_timeout": 5},
        echo=False,
    )
    if engine.url.database is None:
        raise SystemExit("Schema creation blocked: database name is missing.")
    if inspect(engine).has_table(DesktopPaperBot.__tablename__):
        print("Desktop paper bot table already exists.")
        return
    DesktopPaperBot.__table__.create(bind=engine, checkfirst=True)
    print("Created desktop paper bot table; no bots started.")


if __name__ == "__main__":
    main()
