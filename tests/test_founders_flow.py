"""Local integration test: simulated Stripe-paid session -> entitlement -> refund.
Does not contact Stripe or substitute for provider test-mode validation.
"""
import tempfile
import unittest
from pathlib import Path
from app.billing.founders_ledger import FoundersLedger
from app.billing.founders_stripe import PRODUCT_TAG, validate_checkout_session

class FoundersFlowTests(unittest.TestCase):
    def test_checkout_to_entitlement_to_refund(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = FoundersLedger(Path(directory) / "flow.db")
            ledger.reserve("user-1", "reservation-1", now=100)
            session = {
                "id": "cs_test_mock", "payment_intent": "pi_test_mock",
                "mode": "payment", "status": "complete",
                "payment_status": "paid", "amount_total": 25000,
                "currency": "usd",
                "metadata": {"product": PRODUCT_TAG, "account_id": "user-1",
                             "reservation_id": "reservation-1"}
            }
            verified = validate_checkout_session(
                session, expected_account_id="user-1",
                expected_reservation_id="reservation-1"
            )
            first = ledger.confirm_paid(**verified, provider_event_id="evt_1", now=100)
            self.assertEqual(first["founder_number"], 1)
            replay = ledger.confirm_paid(**verified, provider_event_id="evt_1", now=100)
            self.assertEqual(replay["status"], "already_confirmed")
            self.assertTrue(ledger.entitlement("user-1")["lifetime"])
            self.assertTrue(ledger.revoke("pi_test_mock"))
            self.assertIsNone(ledger.entitlement("user-1"))
