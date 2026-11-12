"""SQLite integration tests for inactive, account-scoped desktop paper bots."""
import ast
import tempfile
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace, ModuleType

from sqlalchemy import Boolean, ForeignKey, Numeric, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app" / "api" / "routes" / "desktop.py"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)


class Strategy(Base):
    __tablename__ = "strategies"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)


class PaperWallet(Base):
    __tablename__ = "nexora_paper_wallets"
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), primary_key=True)
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)


class DesktopPaperBot(Base):
    __tablename__ = "nexora_desktop_paper_bots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String, ForeignKey("strategies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    allocated_cash: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    risk_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String, default="configured", nullable=False)


class PaperPreviewPosition(Base):
    __tablename__ = "nexora_preview_positions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    bot_id: Mapped[str] = mapped_column(String, nullable=False)
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    entry_fee: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)


def load_create():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_desktop_paper_bot")
    fn.decorator_list = []
    for arg in fn.args.args:
        arg.annotation = None
    fn.args.defaults = []
    ns = {
        "Strategy": Strategy,
        "PaperWallet": PaperWallet,
        "DesktopPaperBot": DesktopPaperBot,
        "Decimal": Decimal,
        "HTTPException": HTTPException,
    }
    import sys
    fake_preview = ModuleType("app.models.paper_preview")
    fake_preview.PaperPreviewPosition = PaperPreviewPosition
    sys.modules.setdefault("app.models.paper_preview", fake_preview)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(SOURCE), "exec"), ns)
    return ns["create_desktop_paper_bot"]


class DesktopPaperBotSqliteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "bots.db"))
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.create = load_create()
        with self.Session.begin() as db:
            db.add_all([User(id="alice"), User(id="bob")])
            db.add_all([
                Strategy(id="alice-strategy", user_id="alice", symbol="BTC/USD", timeframe="15m"),
                Strategy(id="bob-strategy", user_id="bob", symbol="BTC/USD", timeframe="15m"),
            ])
            db.add_all([
                PaperWallet(user_id="alice", cash_balance=Decimal("1000.00")),
                PaperWallet(user_id="bob", cash_balance=Decimal("1000.00")),
            ])

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def payload(self, **changes):
        data = dict(name="Paper BTC", strategy_id="alice-strategy", symbol="BTC/USD",
                    timeframe="15m", allocated_cash=Decimal("400"), risk_percent=Decimal("1"))
        data.update(changes)
        return SimpleNamespace(**data)

    def test_creates_disabled_paper_bot_without_exchange_key(self):
        with self.Session() as db:
            result = self.create(self.payload(), db, SimpleNamespace(id="alice"))
            self.assertFalse(result["is_enabled"])
            self.assertEqual(result["status"], "configured")
            self.assertEqual(result["mode"], "paper")
            self.assertEqual(db.query(DesktopPaperBot).count(), 1)

    def test_rejects_overallocation_without_persisting(self):
        with self.Session() as db:
            self.create(self.payload(allocated_cash=Decimal("700")), db, SimpleNamespace(id="alice"))
            with self.assertRaises(HTTPException) as caught:
                self.create(self.payload(allocated_cash=Decimal("400")), db, SimpleNamespace(id="alice"))
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(db.query(DesktopPaperBot).count(), 1)

    def test_rejects_another_users_strategy(self):
        with self.Session() as db:
            with self.assertRaises(HTTPException) as caught:
                self.create(self.payload(strategy_id="bob-strategy"), db, SimpleNamespace(id="alice"))
            self.assertEqual(caught.exception.status_code, 404)
            self.assertEqual(db.query(DesktopPaperBot).count(), 0)

    def test_rejects_mismatched_market_and_timeframe(self):
        with self.Session() as db:
            with self.assertRaises(HTTPException) as caught:
                self.create(self.payload(symbol="ETH/USD"), db, SimpleNamespace(id="alice"))
            self.assertEqual(caught.exception.status_code, 422)

    def test_cross_account_bot_records_do_not_consume_other_wallet(self):
        with self.Session() as db:
            self.create(self.payload(strategy_id="bob-strategy", allocated_cash=Decimal("900")),
                        db, SimpleNamespace(id="bob"))
            result = self.create(self.payload(allocated_cash=Decimal("900")),
                                 db, SimpleNamespace(id="alice"))
            self.assertEqual(result["allocated_cash"], 900)
            self.assertEqual(db.query(DesktopPaperBot).count(), 2)

    def test_rejects_bot_without_initialized_wallet(self):
        with self.Session() as db:
            db.query(PaperWallet).filter(PaperWallet.user_id == "alice").delete()
            db.commit()
            with self.assertRaises(HTTPException) as caught:
                self.create(self.payload(), db, SimpleNamespace(id="alice"))
            self.assertEqual(caught.exception.status_code, 409)

    def test_allocations_are_separate_by_account(self):
        with self.Session() as db:
            self.create(self.payload(allocated_cash=Decimal("900")), db, SimpleNamespace(id="alice"))
            result = self.create(self.payload(strategy_id="bob-strategy", allocated_cash=Decimal("900")),
                                 db, SimpleNamespace(id="bob"))
            self.assertEqual(result["allocated_cash"], 900)
            self.assertEqual(db.query(DesktopPaperBot).count(), 2)


if __name__ == "__main__":
    unittest.main()
