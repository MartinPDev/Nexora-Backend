import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ccxt

from app import asset_bot_engine as engine
from app import asset_bot_supervisor as supervisor
from app.core.json_store import load_json, save_json


def make_bot(index: int) -> dict:
    return {
        "username": "restart-user",
        "id": f"bot-{index}",
        "name": f"Bot {index}",
        "symbol": "BTC/USD",
        "bot_type": "asset_specific",
        "enabled": True,
        "current_open_positions": 0,
    }


class RestartRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.bots_file = str(root / "bots.json")
        self.positions_file = str(root / "positions.json")
        self.logs_file = str(root / "logs.json")
        self.trades_file = str(root / "trades.json")
        self.patchers = [
            patch.object(engine, "BOTS_FILE", self.bots_file),
            patch.object(engine, "POSITIONS_FILE", self.positions_file),
            patch.object(engine, "LOGS_FILE", self.logs_file),
            patch.object(engine, "TRADES_FILE", self.trades_file),
            patch.object(supervisor, "BOTS_FILE", self.bots_file),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.directory.cleanup()

    def reconcile(self, bots, positions=None):
        save_json(self.bots_file, {"restart-user": bots} if bots else {})
        save_json(self.positions_file, positions or {})
        return supervisor.reconcile_runtime_state()

    def test_restart_with_zero_bots(self):
        result = self.reconcile([])
        self.assertEqual(result["active_bots"], 0)
        self.assertEqual(result["open_positions"], 0)

    def test_restart_with_one_bot_and_open_position(self):
        bot = make_bot(1)
        position = {"restart-user:bot-1": {"username": "restart-user", "bot_id": "bot-1", "symbol": "BTC/USD", "status": "open"}}
        result = self.reconcile([bot], position)
        restored = load_json(self.bots_file, {})["restart-user"][0]
        self.assertEqual(result["active_bots"], 1)
        self.assertEqual(result["open_positions"], 1)
        self.assertEqual(restored["current_open_positions"], 1)
        self.assertEqual(restored["last_action"], "Recovered open position")

    def test_restart_with_ten_bots(self):
        bots = [make_bot(index) for index in range(10)]
        result = self.reconcile(bots)
        restored = load_json(self.bots_file, {})["restart-user"]
        self.assertEqual(result["active_bots"], 10)
        self.assertEqual(len(restored), 10)
        self.assertTrue(all(bot["status"] == "active" for bot in restored))

    def test_restart_does_not_duplicate_persisted_open_trade(self):
        bot = make_bot(1)
        position = {"restart-user:bot-1": {"username": "restart-user", "bot_id": "bot-1", "symbol": "BTC/USD", "entry_price": 100.0, "amount": 1.0, "allocated_cash": 100.0, "status": "open"}}
        self.reconcile([bot], position)
        with patch.object(engine, "fetch_price", return_value=101.0):
            engine.scan_all_enabled_bots()
        positions = load_json(self.positions_file, {})
        self.assertEqual(list(positions), ["restart-user:bot-1"])
        self.assertEqual(positions["restart-user:bot-1"]["entry_price"], 100.0)

    def test_kraken_unavailable_keeps_all_bots_enabled(self):
        bots = [make_bot(index) for index in range(3)]
        self.reconcile(bots)
        with patch.object(engine, "fetch_price", side_effect=ccxt.NetworkError("simulated outage")):
            result = engine.scan_all_enabled_bots()
        restored = load_json(self.bots_file, {})["restart-user"]
        self.assertEqual(result["count"], 0)
        self.assertEqual(len(restored), 3)
        self.assertTrue(all(bot["enabled"] for bot in restored))


if __name__ == "__main__":
    unittest.main()