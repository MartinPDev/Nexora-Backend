# Nexora v0.3.3 local Paper Preview integration

**Scope:** local PostgreSQL `cryptobot`, recovered Electron v0.3.3, Kraken public OHLC, paper only. No live exchange orders, no production deployment, and no changes to `app/main.py` or `app/bot3.py`.

## Before starting the recovered desktop

1. Confirm the existing local PostgreSQL backup is intact and restorable. Never apply schema changes to production or to the unrelated Sniper database.
2. Review `scripts/sql/preview_paper_v1.sql`. It creates three durable preview tables, an owner index, proposal uniqueness, and a partial unique index allowing at most one open position per bot. Apply **only** to the local `cryptobot` database after backup verification. Do not let desktop startup silently migrate the database.
3. Configure the existing local backend settings with `NEXORA_LOCAL_DESKTOP_API=YES`, local PostgreSQL `cryptobot`, and a non-production environment. To opt into background proposal detection and protective settlement, also set `NEXORA_PREVIEW_WORKER=YES`; otherwise manual scanning and settlement remain available.
4. Run `python -m scripts.check_preview_schema` before starting the API. This read-only check verifies all required tables, columns, and the single-open-position index.
5. Start the isolated API with `python -m uvicorn scripts.local_desktop_api:app --host 127.0.0.1 --port 8765`. Configure the desktop's API origin and prefix to match the local server.

## Functional verification

- Authenticate as the intended account and verify that the wallet starts at $1,000 only once. Restart and verify the balance does not reset.
- Create an existing account-owned strategy matching a supported Kraken market/timeframe. Create a paper bot with allocation and risk within available cash.
- Enroll the bot in Paper Preview. Scan only completed Kraken candles. Most scans should reject; **never fabricate a proposal** to make the screen appear active.
- When a genuine proposal appears, confirm it displays price, quantity, estimated fees, expiry and immutable payload hash. Confirm a wrong hash, expired proposal, duplicate approval, and other-user access are rejected.
- Approve one proposal and verify exactly one simulated position, a single wallet debit, and correct reservation accounting. Use manual protective-exit checks or the opt-in observer. Verify settlement credits proceeds once, records fees and P&L, and rejects replay.
- Verify the three Kraken charts, market watchlist, portfolio, bot controls, and trade history. Unknown valuation must display **Unavailable**, not $0.
- Repeat after API and desktop restart to verify persistence.

## Limitations

- An unsigned installer may trigger Windows SmartScreen. CI builds are test artifacts only, not a signed or published release.
- The local observer requires the explicit worker flag and a running local API process. No observer can approve trades.
- Current entry rules use deterministic EMA9/EMA20 crossovers. This is **not** validated AI trading, does not implement every strategy scoring gate, and does not prove profitability.
- The application has not yet been verified against the owner's actual local PostgreSQL accounts and Windows environment. Passing CI cannot substitute for that check.
