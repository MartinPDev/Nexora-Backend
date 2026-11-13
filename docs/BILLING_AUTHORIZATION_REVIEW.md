# Billing authorization review — 2026-11-13

Scope: Nexora-Backend app/main.py and opt-in Founders Edition routes, reviewed on the development branch. This is not a complete security audit.

## Remediated in development branch
- POST /billing/{username}/set-plan/{plan}: now always returns 403; previously granted paid entitlements without proof of payment.
- Legacy POST /billing/{username}/checkout/*: now 403; previously trusted arbitrary username and hard-coded localhost return URLs.
- GET /billing/{username}: now requires a session token resolving to the same username.
- Legacy POST /stripe/webhook: now 503 until replaced; previously activated plans using unverified metadata without idempotent fulfillment.
- Founders routes: require legacy session ownership, Stripe test-mode key, verified USD 250 one-time price, signed event and provider-retrieved paid checkout session.
- Founders entitlement: backend-owned lookup, with refund/dispute revocation and immutable historical founder allocation.

## Remaining launch blockers (do not merge/deploy)
1. Legacy SESSIONS is an in-memory dictionary; review session creation, expiry, revocation, CSRF exposure, session fixation, and restart behavior. Migrate Founders to canonical authenticated API identity.
2. Audit ALL account-scoped endpoints (bots, trading, dashboard, strategies, settings) for horizontal privilege escalation. A billing-only patch does not secure the rest of the API.
3. Legacy signup-basic checkout still creates subscriptions; review account registration, payment status, and webhook handling before enabling any commercial checkout.
4. Stripe checkout session expires in one hour. Repeated attempts must reuse or reconcile the existing Stripe session; the current reservation model is not a durable checkout-session mapping.
5. Delayed successful payments after reservation expiry need a reconciliation/refund path that cannot issue a 51st lifetime membership. A payment must not be silently lost.
6. Refund/dispute handler must validate that a refund/dispute belongs to a Founders Edition payment and implement dispute-won restoration and partial-refund policy.
7. Billing JSON updates are not transactional and cannot safely be used as the final source of subscription entitlements.
8. Genuine Stripe TEST environment: configure test price, webhook signing secret, HTTPS callback, authenticated test user; verify success, cancel, expired checkout, duplicate event, refund, dispute, concurrency and failed payments. No live credentials.
9. Do not enable live trading merely because a user has Elite entitlement; retain explicit independent trading enablement and risk controls.
10. Desktop v0.3.3 hardened working source is not present in the connected GitHub repo. The recovery ZIPs are older and still expose renderer token APIs. Integrate entitlement display only into the current hardened source after obtaining it.

## Acceptance gate
All tests passing on latest commit, staging test-mode payment/refund verified with Stripe event IDs, security review of all user-scoped routes complete, desktop hardened integration tested, pricing/terms approved, and explicit owner authorization for deployment.
