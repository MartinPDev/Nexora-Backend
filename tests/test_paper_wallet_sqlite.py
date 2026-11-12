"""Isolated SQLite integration tests for Nexora paper-wallet initialization.

Runs against a temporary database, never the production database or Sniper Bot.
"""
import ast
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import patch

from sqlalchemy import create_engine, String, Numeric, ForeignKey, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "app" / "api" / "routes" / "desktop.py"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)


class DesktopPaperBot(Base):
    __tablename__ = "nexora_desktop_paper_bots"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    allocated_cash: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)


class PaperWallet(Base):
    __tablename__ = "nexora_paper_wallets"
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), primary_key=True)
    initial_balance: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)


class PaperPreviewPosition(Base):
    __tablename__ = "nexora_preview_positions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    bot_id: Mapped[str] = mapped_column(String, nullable=False)
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    entry_fee: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)


def load_portfolio_function():
    tree = ast.parse(DESKTOP.read_text(encoding="utf-8"))
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "desktop_portfolio"]
    if len(matches) != 1:
        raise AssertionError("Expected one desktop portfolio route")
    fn = matches[0]
    fn.decorator_list = []
    # Dependency injection defaults are only relevant to FastAPI; pass real args directly.
    for arg in fn.args.args:
        arg.annotation = None
    fn.args.defaults = []
    ns = {"PaperWallet": PaperWallet, "DesktopPaperBot": DesktopPaperBot, "Decimal": Decimal, "IntegrityError": IntegrityError}
    # Isolate the route from application settings and production DB imports.
    fake_preview = ModuleType("app.models.paper_preview")
    fake_preview.PaperPreviewPosition = PaperPreviewPosition
    import sys
    sys.modules.setdefault("app.models.paper_preview", fake_preview)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(DESKTOP), "exec"), ns)
    return ns["desktop_portfolio"]


class PaperWalletSqliteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "wallet.db"))
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.portfolio = load_portfolio_function()
        with self.Session.begin() as db:
            db.add_all([User(id="alice"), User(id="bob")])

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_first_visit_creates_exactly_one_thousand_dollars(self):
        with self.Session() as db:
            result = self.portfolio(db, SimpleNamespace(id="alice"))
            self.assertEqual(result["cash"], 1000.0)
            self.assertEqual(result["financial_data_status"], "cash_and_reservations_only")
            self.assertIsNone(result["total_value"])
            self.assertIsNone(result["unrealized_pnl"])
            self.assertEqual(db.query(PaperWallet).count(), 1)

    def test_repeat_visits_do_not_refund_or_reset_wallet(self):
        with self.Session() as db:
            self.portfolio(db, SimpleNamespace(id="alice"))
            wallet = db.get(PaperWallet, "alice")
            wallet.cash_balance = Decimal("725.25")
            db.commit()
        with self.Session() as db:
            self.assertEqual(self.portfolio(db, SimpleNamespace(id="alice"))["cash"], 725.25)
            self.assertEqual(db.query(PaperWallet).count(), 1)

    def test_accounts_have_separate_wallets(self):
        with self.Session() as db:
            self.portfolio(db, SimpleNamespace(id="alice"))
            self.portfolio(db, SimpleNamespace(id="bob"))
            self.assertEqual(db.query(PaperWallet).count(), 2)
            self.assertEqual({w.user_id for w in db.query(PaperWallet).all()}, {"alice", "bob"})

    def test_reserved_cash_reduces_available_without_changing_wallet_balance(self):
        with self.Session() as db:
            self.portfolio(db, SimpleNamespace(id="alice"))
            db.add(DesktopPaperBot(id="paper-1", user_id="alice", allocated_cash=Decimal("600")))
            db.commit()
        with self.Session() as db:
            result = self.portfolio(db, SimpleNamespace(id="alice"))
            self.assertEqual(result["cash"], 400)
            self.assertEqual(result["reserved_cash"], 600)
            self.assertEqual(result["paper_cash_balance"], 1000)
            self.assertIsNone(result["total_value"])

    def test_wallet_persists_after_session_reopens(self):
        with self.Session() as db:
            self.portfolio(db, SimpleNamespace(id="alice"))
        with self.Session() as db:
            wallet = db.get(PaperWallet, "alice")
            self.assertEqual(wallet.initial_balance, Decimal("1000.00000000"))


if __name__ == "__main__":
    unittest.main()
