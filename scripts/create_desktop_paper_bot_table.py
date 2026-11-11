"""Explicit schema creation for isolated Nexora desktop paper bots."""
from sqlalchemy import inspect
from app.core.database import engine
from app.models.desktop_paper_bot import DesktopPaperBot


def main():
    if inspect(engine).has_table(DesktopPaperBot.__tablename__):
        print("Desktop paper bot table already exists.")
        return
    DesktopPaperBot.__table__.create(bind=engine, checkfirst=True)
    print("Created desktop paper bot table; no bots started.")


if __name__ == "__main__":
    main()
