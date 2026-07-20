# Nexora Beta Readiness

## Release scope

- Paper trading and simulation only.
- Kraken public market data only.
- `app/bot3.py` is the asset-bot intelligence/runtime contract used by the backend supervisor.
- Account creation is restricted to users aged 18 or older.
- Live exchange-order execution is not enabled in this beta.

## Automated verification

- Python source compilation.
- Browser JavaScript syntax validation.
- JSON persistence concurrency and recovery tests.
- Asset-bot duplicate-open, manual-close, outage, and restart tests.
- Rapid Scalper cost, target, stop, expiry, and direction tests.
- Age eligibility boundary and leap-day tests.
- PBKDF2 password verification and legacy-account compatibility tests.

## Required before starting the beta server

1. Create `.env` from `.env.example`.
2. Replace every placeholder secret and database credential.
3. Set `NEXORA_PUBLIC_BASE_URL` and `CORS_ORIGINS` to the HTTPS beta domain.
4. Install the pinned `requirements.txt` in a clean virtual environment.
5. Back up the existing SQLite/JSON state before first startup.
6. Start against a staging copy of the data and confirm the startup migrations.
7. Complete browser testing for registration, login, charts, asset bots, and Rapid Scalper.
8. Confirm `/health` is healthy and review logs for one complete supervisor cycle.

## Beta acceptance checks

- Under-18 registration is rejected by both registration APIs.
- Adult registration stores the supplied date of birth.
- Existing accounts can still authenticate after password hardening.
- The asset-bot supervisor imports `app.bot3`, not the legacy engine.
- Manual paper close records exactly one trade and pauses automatic re-entry.
- Fullscreen charts return to their grid cells without overlap.
- Rapid Scalper PnL changes during its 45-second paper simulation.
- No plan advertises or enables live trading.
