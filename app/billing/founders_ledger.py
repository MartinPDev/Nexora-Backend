"""Founders Edition inventory and entitlement ledger. Not wired to production routes."""
import sqlite3
import time
from contextlib import contextmanager

LIMIT = 50
AMOUNT_CENTS = 25000
CURRENCY = "usd"
RESERVATION_SECONDS = 30 * 60

class FoundersSoldOut(Exception):
    pass

class InvalidPayment(Exception):
    pass

class FoundersLedger:
    def __init__(self, database_path):
        self.database_path = str(database_path)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS founder_reservations (
                account_id TEXT PRIMARY KEY,
                reservation_id TEXT NOT NULL UNIQUE,
                expires_at INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS founder_purchases (
                founder_number INTEGER PRIMARY KEY CHECK(founder_number BETWEEN 1 AND 50),
                account_id TEXT NOT NULL UNIQUE,
                provider_payment_id TEXT NOT NULL UNIQUE,
                amount_cents INTEGER NOT NULL CHECK(amount_cents = 25000),
                currency TEXT NOT NULL CHECK(currency = 'usd'),
                purchased_at INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS founder_events (
                provider_event_id TEXT PRIMARY KEY,
                provider_payment_id TEXT NOT NULL,
                recorded_at INTEGER NOT NULL
            )""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
        finally:
            db.close()

    def reserve(self, account_id, reservation_id, now=None):
        if not account_id or not reservation_id:
            raise ValueError("Account and reservation identifiers required")
        now = int(time.time() if now is None else now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("DELETE FROM founder_reservations WHERE expires_at <= ?", (now,))
                existing = db.execute(
                    "SELECT founder_number FROM founder_purchases WHERE account_id=?", (account_id,)
                ).fetchone()
                if existing:
                    db.execute("COMMIT")
                    return {"status": "purchased", "founder_number": existing["founder_number"]}
                existing = db.execute(
                    "SELECT reservation_id, expires_at FROM founder_reservations WHERE account_id=?", (account_id,)
                ).fetchone()
                if existing:
                    db.execute("COMMIT")
                    return {"status": "reserved", "reservation_id": existing["reservation_id"], "expires_at": existing["expires_at"]}
                used = db.execute("SELECT COUNT(*) FROM founder_purchases").fetchone()[0]
                reserved = db.execute("SELECT COUNT(*) FROM founder_reservations").fetchone()[0]
                if used + reserved >= LIMIT:
                    raise FoundersSoldOut("All 50 Founders Edition slots are allocated")
                expires_at = now + RESERVATION_SECONDS
                db.execute(
                    "INSERT INTO founder_reservations VALUES (?, ?, ?)",
                    (account_id, reservation_id, expires_at)
                )
                db.execute("COMMIT")
                return {"status": "reserved", "reservation_id": reservation_id, "expires_at": expires_at}
            except Exception:
                db.execute("ROLLBACK")
                raise

    def confirm_paid(self, *, account_id, reservation_id, provider_payment_id,
                     provider_event_id, amount_cents, currency, paid, now=None):
        """Call ONLY after independently verifying a signed provider event and checkout details."""
        if (not paid or type(amount_cents) is not int or amount_cents != AMOUNT_CENTS
                or currency != CURRENCY or not all(
                    isinstance(v, str) and v.strip()
                    for v in (account_id, reservation_id, provider_payment_id, provider_event_id)
                )):
            raise InvalidPayment("Payment details do not match Founders Edition")
        now = int(time.time() if now is None else now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute(
                    "SELECT founder_number, account_id FROM founder_purchases WHERE provider_payment_id=?",
                    (provider_payment_id,)
                ).fetchone()
                if existing:
                    if existing["account_id"] != account_id:
                        raise InvalidPayment("Payment already assigned to another account")
                    db.execute("COMMIT")
                    return {"status": "already_confirmed", "founder_number": existing["founder_number"]}
                existing = db.execute(
                    "SELECT founder_number FROM founder_purchases WHERE account_id=?", (account_id,)
                ).fetchone()
                if existing:
                    raise InvalidPayment("Account already owns a founding membership")
                reservation = db.execute(
                    "SELECT reservation_id FROM founder_reservations WHERE account_id=?", (account_id,)
                ).fetchone()
                if not reservation or reservation["reservation_id"] != reservation_id:
                    raise InvalidPayment("No matching reservation for payment")
                used = {row[0] for row in db.execute("SELECT founder_number FROM founder_purchases")}
                founder_number = next((n for n in range(1, LIMIT + 1) if n not in used), None)
                if founder_number is None:
                    raise FoundersSoldOut("Founders Edition is sold out")
                db.execute(
                    "INSERT INTO founder_purchases VALUES (?, ?, ?, ?, ?, ?)",
                    (founder_number, account_id, provider_payment_id, amount_cents, currency, now)
                )
                db.execute(
                    "INSERT INTO founder_events VALUES (?, ?, ?)",
                    (provider_event_id, provider_payment_id, now)
                )
                db.execute("DELETE FROM founder_reservations WHERE account_id=?", (account_id,))
                db.execute("COMMIT")
                return {"status": "confirmed", "founder_number": founder_number}
            except Exception:
                db.execute("ROLLBACK")
                raise

    def entitlement(self, account_id):
        with self._db() as db:
            row = db.execute(
                "SELECT founder_number FROM founder_purchases WHERE account_id=?", (account_id,)
            ).fetchone()
            return {"plan": "elite", "lifetime": True, "founder_number": row["founder_number"]} if row else None

    def availability(self, now=None):
        now = int(time.time() if now is None else now)
        with self._db() as db:
            confirmed = db.execute("SELECT COUNT(*) FROM founder_purchases").fetchone()[0]
            reserved = db.execute(
                "SELECT COUNT(*) FROM founder_reservations WHERE expires_at > ?", (now,)
            ).fetchone()[0]
            return {"limit": LIMIT, "confirmed": confirmed, "available": max(0, LIMIT - confirmed - reserved)}
