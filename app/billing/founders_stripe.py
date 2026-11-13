"""Stripe Founders Edition event validation, intentionally not mounted in app/main.py.

The caller MUST first verify Stripe's signature against raw request bytes, then
retrieve the Checkout Session from Stripe with the configured secret key.
"""
from .founders_ledger import AMOUNT_CENTS, CURRENCY, InvalidPayment

PRODUCT_TAG = "nexora_founders_edition_v1"

def validate_checkout_session(session, *, expected_account_id, expected_reservation_id):
    """Validate a server-retrieved Stripe Checkout Session; returns ledger arguments.

    Does not accept untrusted browser redirect parameters or webhook metadata
    as proof of payment.
    """
    def field(obj, name, default=None):
        return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)

    metadata = field(session, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = dict(metadata)
    session_id = field(session, "id")
    payment_intent = field(session, "payment_intent")
    if not all(isinstance(v, str) and v for v in
               (session_id, payment_intent, expected_account_id, expected_reservation_id)):
        raise InvalidPayment("Missing session, payment, account, or reservation identifier")
    if (field(session, "mode") != "payment"
            or field(session, "status") != "complete"
            or field(session, "payment_status") != "paid"
            or field(session, "amount_total") != AMOUNT_CENTS
            or field(session, "currency") != CURRENCY
            or metadata.get("product") != PRODUCT_TAG
            or metadata.get("account_id") != expected_account_id
            or metadata.get("reservation_id") != expected_reservation_id):
        raise InvalidPayment("Checkout Session does not match the Founders Edition purchase")
    return {
        "account_id": expected_account_id,
        "reservation_id": expected_reservation_id,
        "provider_payment_id": payment_intent,
        "amount_cents": AMOUNT_CENTS,
        "currency": CURRENCY,
        "paid": True,
    }
