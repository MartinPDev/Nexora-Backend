"""Execute the real completed-candle scan against SQLite, with synthetic Kraken candles."""
import ast
import asyncio
import hashlib
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from test_preview_approval_sqlite import (
    Base, User, PaperWallet, DesktopPaperBot,
    PaperPreviewProposal, PaperPreviewPosition, HTTPException,
)

SOURCE = Path(__file__).resolve().parents[1] / "app/api/routes/paper_preview.py"


def candles(crossover):
    now = int(datetime.utcnow().timestamp())
    rows = []
    for i in range(82):
        price = 110 if crossover and i == 80 else 100
        rows.append({"timestamp": now - (81 - i) * 900,
                     "open": price, "high": price, "low": price,
                     "close": price, "volume": 1})
    return rows


def load_scan(rows):
    tree = ast.parse(SOURCE.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "scan")
    fn.decorator_list = []
    for arg in fn.args.args:
        arg.annotation = None
    fn.args.defaults = []
    def bot_owned(db, user, bot_id):
        bot = db.query(DesktopPaperBot).filter(DesktopPaperBot.id == bot_id, DesktopPaperBot.user_id == user.id).first()
        if bot is None:
            raise HTTPException(404, "Not found")
        return bot
    record = SimpleNamespace(last_action=None, last_reason=None, last_scanned_at=None)
    def enrollment(db, user, bot_id):
        return record
    def ema(values, period):
        result = sum(values[:period]) / Decimal(period)
        for value in values[period:]:
            result += (value - result) * Decimal(2) / Decimal(period + 1)
        return result
    def serial_proposal(p):
        return {"proposal_id": p.id, "payload_hash": p.payload_hash, "status": p.status}
    namespace = {
        "bot_owned": bot_owned, "enrollment": enrollment,
        "PaperPreviewPosition": PaperPreviewPosition,
        "PaperPreviewProposal": PaperPreviewProposal,
        "HTTPException": HTTPException, "IntegrityError": IntegrityError,
        "datetime": datetime, "timedelta": timedelta, "uuid": uuid,
        "asyncio": asyncio, "hashlib": hashlib, "json": json,
        "D": Decimal, "ROUND_DOWN": ROUND_DOWN,
        "MONEY": Decimal("0.00000001"), "FEE_RATE": Decimal("0.0026"),
        "_KRAKEN_PAIRS": {"BTC/USD": "XBTUSD"},
        "_KRAKEN_INTERVALS": {"15m": 15},
        "_fetch_kraken_candles": lambda pair, interval: rows,
        "ema": ema, "serial_proposal": serial_proposal,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(SOURCE), "exec"), namespace)
    return namespace["scan"], record


class ScanIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "scan.db"))
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session.begin() as db:
            db.add(User(id="alice"))
            db.add(PaperWallet(user_id="alice", cash_balance=Decimal("1000")))
            db.add(DesktopPaperBot(id="bot-1", user_id="alice", allocated_cash=Decimal("200")))

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_crossover_creates_one_proposal_but_no_position_or_cash_debit(self):
        scan, record = load_scan(candles(True))
        with self.Session() as db:
            result = asyncio.run(scan("bot-1", db, SimpleNamespace(id="alice")))
            self.assertEqual(result["action"], "PROPOSE")
            self.assertEqual(record.last_action, "PROPOSE")
            self.assertEqual(db.query(PaperPreviewProposal).count(), 1)
            self.assertEqual(db.query(PaperPreviewPosition).count(), 0)
            self.assertEqual(db.get(PaperWallet, "alice").cash_balance, Decimal("1000"))
            with self.assertRaises(HTTPException) as error:
                asyncio.run(scan("bot-1", db, SimpleNamespace(id="alice")))
            self.assertEqual(error.exception.status_code, 409)

    def test_no_crossover_rejects_without_proposal(self):
        scan, record = load_scan(candles(False))
        with self.Session() as db:
            result = asyncio.run(scan("bot-1", db, SimpleNamespace(id="alice")))
            self.assertEqual(result["action"], "REJECT")
            self.assertEqual(record.last_action, "REJECT")
            self.assertEqual(db.query(PaperPreviewProposal).count(), 0)


if __name__ == "__main__":
    unittest.main()
