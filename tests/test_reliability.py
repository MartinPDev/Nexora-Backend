import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import ccxt

from app import asset_bot_engine as engine
from app.core.json_store import load_json, save_json, update_json


class JsonStoreTests(unittest.TestCase):
    def test_corrupt_primary_recovers_from_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "state.json")
            save_json(path, {"version": 1})
            save_json(path, {"version": 2})
            Path(path).write_text("{broken", encoding="utf-8")

            recovered = load_json(path, {})

            self.assertEqual(recovered, {"version": 1})
            self.assertEqual(json.loads(Path(path).read_text()), {"version": 1})

    def test_concurrent_updates_do_not_lose_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "counter.json")
            save_json(path, {"count": 0})

            def increment():
                for _ in range(25):
                    update_json(
                        path,
                        {"count": 0},
                        lambda value: {"count": value["count"] + 1},
                    )

            threads = [threading.Thread(target=increment) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(load_json(path, {})["count"], 100)


class AssetBotReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.paths = {
            "BOTS_FILE": str(root / "bots.json"),
            "POSITIONS_FILE": str(root / "positions.json"),
            "TRADES_FILE": str(root / "trades.json"),
            "LOGS_FILE": str(root / "logs.json"),
        }
        self.patchers = [
            patch.object(engine, name, value)
            for name, value in self.paths.items()
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.directory.cleanup()

    def test_duplicate_position_is_prevented_under_concurrency(self):
        bot = {
            "username": "beta-user",
            "id": "bot-1",
            "name": "BTC Bot",
            "symbol": "BTC/USD",
            "allocated_cash": 100,
        }
        save_json(self.paths["BOTS_FILE"], {"beta-user": [bot]})

        threads = [
            threading.Thread(target=engine.open_paper_position, args=(bot, 50))
            for _ in range(5)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        positions = load_json(self.paths["POSITIONS_FILE"], {})
        self.assertEqual(list(positions), ["beta-user:bot-1"])

    def test_one_bot_failure_does_not_stop_other_bots(self):
        bots = [
            {
                "username": "beta-user",
                "id": "bad",
                "symbol": "BAD/USD",
                "bot_type": "asset_specific",
                "enabled": True,
            },
            {
                "username": "beta-user",
                "id": "good",
                "symbol": "BTC/USD",
                "bot_type": "asset_specific",
                "enabled": True,
            },
        ]
        save_json(self.paths["BOTS_FILE"], {"beta-user": bots})

        def fake_scan(bot):
            if bot["id"] == "bad":
                raise RuntimeError("simulated bot failure")
            return {"bot_id": bot["id"], "status": "ok"}

        with patch.object(engine, "scan_asset_bot", side_effect=fake_scan):
            result = engine.scan_all_enabled_bots()

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["bot_id"], "good")

    def test_exchange_failure_retries_then_recovers(self):
        exchange = unittest.mock.Mock()
        exchange.fetch_ticker.side_effect = [
            ccxt.RequestTimeout("timeout"),
            ccxt.RateLimitExceeded("limited"),
            {"last": 123.45},
        ]

        with patch.object(engine.ccxt, "kraken", return_value=exchange), patch.object(
            engine.time, "sleep"
        ):
            price = engine.fetch_price("BTC/USD")

        self.assertEqual(price, 123.45)
        self.assertEqual(exchange.fetch_ticker.call_count, 3)


if __name__ == "__main__":
    unittest.main()
