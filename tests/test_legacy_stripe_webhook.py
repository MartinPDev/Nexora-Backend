"""Payment verification regression checks without Stripe network calls."""
import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / "app" / "main.py"


class HTTPError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


class FakeRequest:
    def __init__(self, signature="valid"):
        self.headers = {"stripe-signature": signature} if signature else {}

    async def body(self):
        return b"test"


def webhook(event, subscription=None, secret="whsec_test"):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    funcs = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "stripe_webhook"]
    if len(funcs) != 1:
        raise AssertionError("Missing webhook")
    namespace = {
        "Request": object,
        "HTTPException": HTTPError,
        "STRIPE_WEBHOOK_SECRET": secret,
        "STRIPE_PRICE_IDS": {"pro": "price_pro", "elite": "price_elite"},
        "stripe": SimpleNamespace(
            Webhook=SimpleNamespace(construct_event=Mock(return_value=event)),
            Subscription=SimpleNamespace(retrieve=Mock(return_value=subscription)),
            error=SimpleNamespace(SignatureVerificationError=type("SignatureVerificationError", (Exception,), {})),
        ),
        "activate_user_plan": Mock(return_value={"plan": "pro"}),
    }
    # Execute the handler in isolation without its FastAPI route decorator.
    funcs[0].decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[])), str(SOURCE), "exec"), namespace)
    return namespace


def event(payment="paid", plan="pro"):
    return {
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "payment_status": payment,
            "subscription": "sub_test",
            "metadata": {"username": "alice", "plan": plan},
        }},
    }


class StripeWebhookSecurityTests(unittest.TestCase):
    def invoke(self, namespace, signature="valid"):
        return asyncio.run(namespace["stripe_webhook"](FakeRequest(signature)))

    def test_missing_webhook_secret_fails_closed(self):
        ns = webhook(event(), secret="")
        with self.assertRaises(HTTPError) as caught:
            self.invoke(ns)
        self.assertEqual(caught.exception.status_code, 503)

    def test_missing_signature_rejected(self):
        ns = webhook(event())
        with self.assertRaises(HTTPError) as caught:
            self.invoke(ns, signature="")
        self.assertEqual(caught.exception.status_code, 400)

    def test_unpaid_checkout_does_not_activate(self):
        ns = webhook(event(payment="unpaid"))
        self.assertFalse(self.invoke(ns)["activated"])
        ns["activate_user_plan"].assert_not_called()

    def test_wrong_subscription_price_does_not_activate(self):
        sub = {"status": "active", "items": {"data": [{"price": {"id": "price_other"}}]}}
        ns = webhook(event(), subscription=sub)
        self.assertFalse(self.invoke(ns)["activated"])
        ns["activate_user_plan"].assert_not_called()

    def test_paid_active_matching_subscription_activates(self):
        sub = {"status": "active", "items": {"data": [{"price": {"id": "price_pro"}}]}}
        ns = webhook(event(), subscription=sub)
        self.assertTrue(self.invoke(ns)["activated"])
        ns["activate_user_plan"].assert_called_once_with("alice", "pro")

    def test_elite_maps_to_premium_entitlement(self):
        sub = {"status": "active", "items": {"data": [{"price": {"id": "price_elite"}}]}}
        ns = webhook(event(plan="elite"), subscription=sub)
        self.assertTrue(self.invoke(ns)["activated"])
        ns["activate_user_plan"].assert_called_once_with("alice", "premium")


if __name__ == "__main__":
    unittest.main()
