"""SQLite transaction tests of real protective settlement logic; no exchange or app startup."""
import ast
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import String, Numeric, ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

SOURCE = Path(__file__).resolve().parents[1] / "app/api/routes/paper_preview.py"


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)


class PaperWallet(Base):
    __tablename__ = "wallets"
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), primary_key=True)
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)


class DesktopPaperBot(Base):
    __tablename__ = "bots"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String)
    timeframe: Mapped[str] = mapped_column(String)


class PaperPreviewPosition(Base):
    __tablename__ = "positions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("bots.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    opened_at: Mapped[datetime] = mapped_column(nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    entry_fee: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    peak_price: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    exit_price: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=True)
    exit_fee: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=True)
    pnl: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=True)
    exit_reason: Mapped[str] = mapped_column(String, nullable=True)
    closed_at: Mapped[datetime] = mapped_column(nullable=True)


def load_settle(candles):
    tree = ast.parse(SOURCE.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "settle")
    fn.decorator_list = []
    for arg in fn.args.args:
        arg.annotation = None
    fn.args.defaults = []
    def bot_owned(db, user, bot_id):
        bot = db.query(DesktopPaperBot).filter(DesktopPaperBot.id == bot_id, DesktopPaperBot.user_id == user.id).first()
        if not bot:
            raise HTTPException(404, "Not found")
        return bot
    namespace = {
        "bot_owned": bot_owned, "PaperWallet": PaperWallet,
        "PaperPreviewPosition": PaperPreviewPosition, "D": Decimal,
        "MONEY": Decimal("0.00000001"), "FEE_RATE": Decimal("0.0026"),
        "ROUND_DOWN": "ROUND_DOWN", "datetime": datetime, "timedelta": timedelta,
        "asyncio": asyncio, "HTTPException": HTTPException,
        "_KRAKEN_PAIRS": {"BTC/USD": "XBTUSD"},
        "_KRAKEN_INTERVALS": {"15m": 15},
        "_fetch_kraken_candles": lambda pair, interval: candles,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(SOURCE), "exec"), namespace)
    return namespace["settle"]


class SettlementIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "settle.db"))
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.opened = datetime.utcnow() - timedelta(minutes=45)
        with self.Session.begin() as db:
            db.add(User(id="alice"))
            db.add(PaperWallet(user_id="alice", cash_balance=Decimal("899.74")))
            db.add(DesktopPaperBot(id="bot-1", user_id="alice", symbol="BTC/USD", timeframe="15m"))
            db.add(PaperPreviewPosition(id="pos-1", user_id="alice", bot_id="bot-1",
                symbol="BTC/USD", status="OPEN", opened_at=self.opened,
                entry_price=Decimal("10000"), quantity=Decimal("0.01"),
                principal=Decimal("100"), entry_fee=Decimal("0.26"),
                peak_price=Decimal("10000")))

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def candle(self, low, high, close, open_price=10000):
        return {"timestamp": int((datetime.utcnow() - timedelta(minutes=15)).timestamp()),
                "open": open_price, "low": low, "high": high, "close": close}

    def test_take_profit_credits_cash_once(self):
        rows = [self.candle(9950, 10500, 10400), self.candle(10000, 10000, 10000)]
        settle = load_settle(rows)
        with self.Session() as db:
            result = asyncio.run(settle("bot-1", db, SimpleNamespace(id="alice")))
            self.assertEqual(result["status"], "CLOSED")
            self.assertEqual(result["reason"], "TAKE_PROFIT")
            self.assertEqual(db.get(PaperWallet, "alice").cash_balance, Decimal("1003.46960000"))
            with self.assertRaises(HTTPException) as error:
                asyncio.run(settle("bot-1", db, SimpleNamespace(id="alice")))
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(db.get(PaperWallet, "alice").cash_balance, Decimal("1003.46960000"))

    def test_stop_exit_is_conservative_on_gap_down(self):
        rows = [self.candle(9000, 10000, 9200, open_price=9500),
                self.candle(10000, 10000, 10000)]
        settle = load_settle(rows)
        with self.Session() as db:
            result = asyncio.run(settle("bot-1", db, SimpleNamespace(id="alice")))
            self.assertEqual(result["reason"], "STOP_OR_TRAIL")
            self.assertEqual(result["exit_price"], 9500.0)
            self.assertLess(result["pnl"], 0)


if __name__ == "__main__":
    unittest.main()
