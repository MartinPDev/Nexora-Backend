import threading
import time
from datetime import UTC, datetime


STARTED_AT_MONOTONIC = time.monotonic()
STARTED_AT = datetime.now(UTC).isoformat()
_LOCK = threading.Lock()
_STATE = {
    "engine_running": False,
    "last_engine_cycle": None,
    "last_engine_error": None,
    "active_bots": 0,
    "open_positions": 0,
    "last_kraken_api_success": None,
    "last_kraken_api_failure": None,
    "last_kraken_error": None,
}


def update_health(**values) -> None:
    with _LOCK:
        _STATE.update(values)


def record_kraken_success() -> None:
    update_health(
        last_kraken_api_success=datetime.now(UTC).isoformat(),
        last_kraken_error=None,
    )


def record_kraken_failure(error: Exception) -> None:
    update_health(
        last_kraken_api_failure=datetime.now(UTC).isoformat(),
        last_kraken_error=f"{type(error).__name__}: {error}",
    )


def health_snapshot() -> dict:
    with _LOCK:
        state = dict(_STATE)

    uptime_seconds = round(time.monotonic() - STARTED_AT_MONOTONIC, 3)

    return {
        "status": "healthy" if state["engine_running"] else "degraded",
        "started_at": STARTED_AT,
        "uptime": f"{uptime_seconds:.3f}s",
        "uptime_seconds": uptime_seconds,
        "last_kraken_success": state["last_kraken_api_success"],
        "last_kraken_failure": state["last_kraken_api_failure"],
        **state,
    }
