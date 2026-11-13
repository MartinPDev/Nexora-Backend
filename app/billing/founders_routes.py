"""Opt-in Founders Edition Stripe endpoints. Disabled unless NEXORA_FOUNDERS_STAGING_ENABLED=1.

Requires an authenticated legacy session; production launch must replace this with
the canonical signed-in account identity and complete the security review.
"""
import os
import secrets
import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from .founders_ledger import FoundersLedger, FoundersSoldOut, InvalidPayment
from .founders_stripe import PRODUCT_TAG, validate_checkout_session

router = APIRouter(prefix="/founders", tags=["founders"])

def enabled():
    if os.getenv("NEXORA_FOUNDERS_STAGING_ENABLED") != "1":
        raise HTTPException(status_code=503, detail="Founders checkout is not enabled")

def ledger():
    path = os.getenv("NEXORA_FOUNDERS_DB", "")
    if not path:
        raise HTTPException(status_code=503, detail="Founders database is not configured")
    return FoundersLedger(path)

def authenticated_account(token, sessions):
    account = sessions.get(token or "")
    if not account:
        raise HTTPException(status_code=401, detail="Authenticated session required")
    return account

def make_router(sessions):
    # Router factory avoids importing the existing application's global state.
    routes = APIRouter(prefix="/founders", tags=["founders"])

    @routes.get("/availability")
    def availability():
        enabled()
        return ledger().availability()

    @routes.get("/me")
    def entitlement(x_session_token: str | None = Header(default=None)):
        enabled()
        account = authenticated_account(x_session_token, sessions)
        return {"entitlement": ledger().entitlement(account)}

    @routes.post("/checkout")
    def checkout(x_session_token: str | None = Header(default=None)):
        enabled()
        account = authenticated_account(x_session_token, sessions)
        secret = os.getenv("STRIPE_SECRET_KEY", "")
        price_id = os.getenv("STRIPE_FOUNDERS_PRICE_ID", "")
        origin = os.getenv("NEXORA_FOUNDERS_RETURN_ORIGIN", "").rstrip("/")
        if not secret.startswith("sk_test_") or not price_id or not origin.startswith("https://"):
            raise HTTPException(status_code=503, detail="Stripe test-mode checkout not configured")
        store = ledger()
        reservation_id = secrets.token_urlsafe(32)
        try:
            result = store.reserve(account, reservation_id)
        except FoundersSoldOut:
            raise HTTPException(status_code=409, detail="Founders Edition sold out")
        if result["status"] == "purchased":
            raise HTTPException(status_code=409, detail="Account already has lifetime Elite")
        reservation_id = result["reservation_id"]
        stripe.api_key = secret
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=origin + "/pricing.html?founders=return",
                cancel_url=origin + "/pricing.html?founders=cancel",
                client_reference_id=account,
                metadata={"product": PRODUCT_TAG, "account_id": account,
                          "reservation_id": reservation_id},
                expires_at=result["expires_at"],
                idempotency_key="founders-checkout-" + reservation_id,
            )
        except Exception:
            # Do not release an existing reservation after a retry failure:
            # an earlier checkout might already exist at Stripe.
            raise HTTPException(status_code=502, detail="Checkout provider unavailable; retry later")
        return {"checkout_url": session.url, "reservation_expires_at": result["expires_at"]}

    @routes.post("/stripe-webhook")
    async def webhook(request: Request):
        enabled()
        secret = os.getenv("STRIPE_SECRET_KEY", "")
        signing_secret = os.getenv("STRIPE_FOUNDERS_WEBHOOK_SECRET", "")
        if not secret.startswith("sk_test_") or not signing_secret:
            raise HTTPException(status_code=503, detail="Stripe test-mode webhook not configured")
        payload = await request.body()
        try:
            event = stripe.Webhook.construct_event(
                payload, request.headers.get("stripe-signature"), signing_secret
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            raise HTTPException(status_code=400, detail="Invalid webhook signature or payload")
        if event["type"] not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            return {"received": True}
        incoming = event["data"]["object"]
        stripe.api_key = secret
        try:
            session = stripe.checkout.Session.retrieve(incoming["id"])
            metadata = session.metadata or {}
            account = metadata.get("account_id")
            reservation = metadata.get("reservation_id")
            if metadata.get("product") != PRODUCT_TAG:
                return {"received": True}
            verified = validate_checkout_session(
                session, expected_account_id=account, expected_reservation_id=reservation
            )
            verified["provider_event_id"] = event["id"]
            outcome = ledger().confirm_paid(**verified)
        except (InvalidPayment, FoundersSoldOut):
            # Preserve event for manual investigation/refund; never grant access.
            raise HTTPException(status_code=409, detail="Purchase needs billing review")
        except Exception:
            raise HTTPException(status_code=503, detail="Webhook fulfillment unavailable")
        return {"received": True, "status": outcome["status"]}

    return routes
