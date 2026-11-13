"""Isolated Founders Edition ledger tests; run: python -m unittest discover -s tests -p 'test_founders_ledger.py'"""
import tempfile
import unittest
from pathlib import Path
from app.billing.founders_ledger import FoundersLedger, FoundersSoldOut, InvalidPayment

class FoundersLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = FoundersLedger(Path(self.tmp.name) / "founders.db")

    def pay(self, i, **overrides):
        args = dict(account_id=f"account-{i}", reservation_id=f"reservation-{i}",
                    provider_payment_id=f"payment-{i}", provider_event_id=f"event-{i}",
                    amount_cents=25000, currency="usd", paid=True, now=100)
        args.update(overrides)
        return self.ledger.confirm_paid(**args)

    def test_single_purchase_and_replay(self):
        self.ledger.reserve("account-0", "reservation-0", now=100)
        self.assertEqual(self.pay(0), {"status": "confirmed", "founder_number": 1})
        self.assertEqual(self.pay(0), {"status": "already_confirmed", "founder_number": 1})
        self.assertEqual(self.ledger.entitlement("account-0")["plan"], "elite")
        self.assertTrue(self.ledger.entitlement("account-0")["lifetime"])
        self.assertEqual(self.ledger.availability(now=100)["confirmed"], 1)

    def test_invalid_payment_rejected(self):
        self.ledger.reserve("account-0", "reservation-0", now=100)
        for override in ({"amount_cents": 24999}, {"currency": "cad"},
                         {"paid": False}, {"reservation_id": "wrong"},
                         {"amount_cents": True}):
            with self.subTest(override=override), self.assertRaises(InvalidPayment):
                self.pay(0, **override)
        self.assertIsNone(self.ledger.entitlement("account-0"))

    def test_capacity_is_exactly_fifty(self):
        for i in range(50):
            self.assertEqual(self.ledger.reserve(f"account-{i}", f"reservation-{i}", now=100)["status"], "reserved")
        with self.assertRaises(FoundersSoldOut):
            self.ledger.reserve("account-50", "reservation-50", now=100)
        for i in range(50):
            self.assertEqual(self.pay(i)["founder_number"], i + 1)
        self.assertEqual(self.ledger.availability(now=100)["available"], 0)
        with self.assertRaises(FoundersSoldOut):
            self.ledger.reserve("account-51", "reservation-51", now=100)

    def test_expired_reservation_releases_capacity(self):
        for i in range(50):
            self.ledger.reserve(f"account-{i}", f"reservation-{i}", now=100)
        self.assertEqual(self.ledger.reserve("new", "new-reservation", now=4000)["status"], "reserved")
        self.assertEqual(self.ledger.availability(now=4000)["available"], 49)

    def test_release_requires_matching_reservation(self):
        self.ledger.reserve("account-0", "reservation-0", now=100)
        self.assertFalse(self.ledger.release("account-0", "incorrect"))
        self.assertTrue(self.ledger.release("account-0", "reservation-0"))
        self.assertFalse(self.ledger.release("account-0", "reservation-0"))

    def test_revoke_refunded_payment(self):
        self.ledger.reserve("account-0", "reservation-0", now=100)
        self.pay(0)
        self.assertFalse(self.ledger.revoke("nonexistent"))
        self.assertTrue(self.ledger.revoke("payment-0"))
        self.assertIsNone(self.ledger.entitlement("account-0"))

    def test_cannot_steal_payment(self):
        self.ledger.reserve("account-0", "reservation-0", now=100)
        self.pay(0)
        self.ledger.reserve("account-1", "reservation-1", now=100)
        with self.assertRaises(InvalidPayment):
            self.pay(1, provider_payment_id="payment-0")
        self.assertIsNone(self.ledger.entitlement("account-1"))

if __name__ == "__main__":
    unittest.main()
