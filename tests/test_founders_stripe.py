import unittest
from app.billing.founders_stripe import validate_checkout_session, PRODUCT_TAG
from app.billing.founders_ledger import InvalidPayment

class FoundersStripeValidationTests(unittest.TestCase):
    def setUp(self):
        self.session = {
            "id": "cs_test_1", "payment_intent": "pi_test_1",
            "mode": "payment", "status": "complete", "payment_status": "paid",
            "amount_total": 25000, "currency": "usd",
            "metadata": {"product": PRODUCT_TAG, "account_id": "a", "reservation_id": "r"}
        }

    def validate(self):
        return validate_checkout_session(self.session, expected_account_id="a", expected_reservation_id="r")

    def test_valid_session(self):
        self.assertEqual(self.validate()["provider_payment_id"], "pi_test_1")

    def test_reject_mismatches(self):
        cases = [
            ("mode", "subscription"), ("status", "open"),
            ("payment_status", "unpaid"), ("amount_total", 24999),
            ("currency", "cad"), ("payment_intent", None)
        ]
        for key, value in cases:
            with self.subTest(key=key):
                old = self.session[key]
                self.session[key] = value
                with self.assertRaises(InvalidPayment):
                    self.validate()
                self.session[key] = old

    def test_reject_wrong_product_or_account(self):
        for key, value in (("product", "other"), ("account_id", "other"), ("reservation_id", "other")):
            with self.subTest(key=key):
                old = self.session["metadata"][key]
                self.session["metadata"][key] = value
                with self.assertRaises(InvalidPayment):
                    self.validate()
                self.session["metadata"][key] = old
