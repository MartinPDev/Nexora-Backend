"""Execute real SQLite transactions for approval, replay and owner isolation.

No API server, exchange access, or production database is used.
"""
import ast
import tempfile
import unittest
import uuid
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
    allocated_cash: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    symbol: Mapped[str] = mapped_column(String, default="BTC/USD")
    timeframe: Mapped[str] = mapped_column(String, default="15m")


class PaperPreviewProposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("bots.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String)
    candle_timestamp: Mapped[Decimal] = mapped_column(Numeric(20, 0), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    price: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    payload_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)


class PaperPreviewPosition(Base):
    __tablename__ = "positions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("bots.id"), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), unique=True)
    symbol: Mapped[str] = mapped_column(String)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    entry_fee: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    peak_price: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    status: Mapped[str] = mapped_column(String, default="OPEN", nullable=False)


def load_approval():
    tree = ast.parse(SOURCE.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "approve")
    fn.decorator_list = []
    for arg in fn.args.args:
        arg.annotation = None
    fn.args.defaults = []
    def bot_owned(db, user, bot_id):
        bot = db.query(DesktopPaperBot).filter(DesktopPaperBot.id == bot_id, DesktopPaperBot.user_id == user.id).first()
        if not bot:
            raise HTTPException(404, "Bot not found")
        return bot
    def enrollment(db, user, bot_id):
        return True
    namespace = {
        "PaperWallet": PaperWallet, "PaperPreviewProposal": PaperPreviewProposal,
        "PaperPreviewPosition": PaperPreviewPosition, "HTTPException": HTTPException,
        "D": Decimal, "datetime": datetime, "uuid": uuid,
        "bot_owned": bot_owned, "enrollment": enrollment, "IntegrityError": Exception,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(SOURCE), "exec"), namespace)
    return namespace["approve"]


class ApprovalIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "preview.db"))
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.approve = load_approval()
        with self.Session.begin() as db:
            db.add_all([User(id="alice"), User(id="bob")])
            db.add_all([PaperWallet(user_id="alice", cash_balance=Decimal("1000")),
                        PaperWallet(user_id="bob", cash_balance=Decimal("1000"))])
            db.add(DesktopPaperBot(id="bot-1", user_id="alice", allocated_cash=Decimal("200")))
            db.add(PaperPreviewProposal(id="proposal-1", user_id="alice", bot_id="bot-1",
                symbol="BTC/USD", price=Decimal("10000"), quantity=Decimal("0.01"),
                principal=Decimal("100"), fee=Decimal("0.26"), payload_hash="hash-1",
                status="PENDING", expires_at=datetime.utcnow() + timedelta(minutes=5)))

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_one_approval_debits_cash_once_and_replay_fails(self):
        with self.Session() as db:
            result = self.approve("proposal-1", SimpleNamespace(payload_hash="hash-1"), db, SimpleNamespace(id="alice"))
            self.assertEqual(result["status"], "APPROVED")
            self.assertEqual(db.get(PaperWallet, "alice").cash_balance, Decimal("899.74000000"))
            self.assertEqual(db.query(PaperPreviewPosition).count(), 1)
            with self.assertRaises(HTTPException) as error:
                self.approve("proposal-1", SimpleNamespace(payload_hash="hash-1"), db, SimpleNamespace(id="alice"))
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(db.query(PaperPreviewPosition).count(), 1)

    def test_other_account_cannot_approve(self):
        with self.Session() as db:
            with self.assertRaises(HTTPException) as error:
                self.approve("proposal-1", SimpleNamespace(payload_hash="hash-1"), db, SimpleNamespace(id="bob"))
            self.assertEqual(error.exception.status_code, 404)
            self.assertEqual(db.get(PaperWallet, "bob").cash_balance, Decimal("1000"))

    def test_hash_mismatch_never_debits(self):
        with self.Session() as db:
            with self.assertRaises(HTTPException) as error:
                self.approve("proposal-1", SimpleNamespace(payload_hash="wrong"), db, SimpleNamespace(id="alice"))
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(db.get(PaperWallet, "alice").cash_balance, Decimal("1000"))

    def test_expired_proposal_cannot_open_position(self):
        with self.Session() as db:
            p = db.get(PaperPreviewProposal, "proposal-1")
            p.expires_at = datetime.utcnow() - timedelta(minutes=1)
            db.commit()
            with self.assertRaises(HTTPException) as error:
                self.approve("proposal-1", SimpleNamespace(payload_hash="hash-1"), db, SimpleNamespace(id="alice"))
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(db.query(PaperPreviewPosition).count(), 0)


if __name__ == "__main__":
    unittest.main()
