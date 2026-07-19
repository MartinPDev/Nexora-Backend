import fcntl
import os
import threading
from datetime import UTC, datetime

from app.asset_bot_engine import (
    BOTS_FILE,
    POSITIONS_FILE,
    get_enabled_asset_bots,
    get_position_key,
    load_positions,
    log_event,
    scan_all_enabled_bots,
)
from app.core.json_store import update_json
from app.reliability import update_health


ENGINE_LOCK_FILE = "/tmp/nexora-asset-bot-engine.lock"
ENGINE_INTERVAL_SECONDS = int(os.getenv("ASSET_BOT_ENGINE_INTERVAL_SECONDS", "15"))
_SUPERVISOR_THREAD = None
_SUPERVISOR_GUARD = threading.Lock()


def reconcile_runtime_state() -> dict:
    positions = load_positions()
    enabled_bots = get_enabled_asset_bots()
    enabled_keys = {
        get_position_key(bot["username"], bot["id"])
        for bot in enabled_bots
    }

    orphaned_positions = [
        key for key in positions
        if key not in enabled_keys
    ]

    def mutate(bots):
        for username, user_bots in bots.items():
            for bot in user_bots:
                key = get_position_key(username, bot.get("id"))
                has_position = key in positions
                bot["current_open_positions"] = 1 if has_position else 0
                if bot.get("enabled") is not False:
                    bot["status"] = "active"
                    bot["last_action"] = (
                        "Recovered open position"
                        if has_position
                        else "Recovered - awaiting scan"
                    )
                bot["last_scan"] = bot.get("last_scan")
        return bots

    update_json(BOTS_FILE, {}, mutate)
    update_health(
        active_bots=len(enabled_bots),
        open_positions=len(positions),
    )
    log_event(
        f"Restart recovery completed: {len(enabled_bots)} active bots, "
        f"{len(positions)} open positions, {len(orphaned_positions)} orphaned positions"
    )

    return {
        "active_bots": len(enabled_bots),
        "open_positions": len(positions),
        "orphaned_positions": orphaned_positions,
    }


def _engine_loop() -> None:
    with open(ENGINE_LOCK_FILE, "a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log_event("Asset bot supervisor already active in another process", "WARNING")
            return

        update_health(engine_running=True)
        reconcile_runtime_state()

        try:
            while True:
                try:
                    scan_all_enabled_bots()
                except Exception as error:
                    update_health(
                        last_engine_cycle=datetime.now(UTC).isoformat(),
                        last_engine_error=f"{type(error).__name__}: {error}",
                    )
                    log_event(
                        f"Asset bot engine cycle failed: {type(error).__name__}: {error}",
                        "ERROR",
                    )

                threading.Event().wait(ENGINE_INTERVAL_SECONDS)
        finally:
            update_health(engine_running=False)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def start_asset_bot_supervisor():
    global _SUPERVISOR_THREAD

    with _SUPERVISOR_GUARD:
        if _SUPERVISOR_THREAD and _SUPERVISOR_THREAD.is_alive():
            return _SUPERVISOR_THREAD

        _SUPERVISOR_THREAD = threading.Thread(
            target=_engine_loop,
            name="asset-bot-supervisor",
            daemon=True,
        )
        _SUPERVISOR_THREAD.start()
        return _SUPERVISOR_THREAD
