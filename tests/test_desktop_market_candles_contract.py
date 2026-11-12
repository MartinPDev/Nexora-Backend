"""Offline contract tests for recovered desktop Kraken OHLC integration."""
import ast
import pathlib
import unittest


SOURCE = (pathlib.Path(__file__).resolve().parents[1]
          / "app" / "api" / "routes" / "desktop.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


class KrakenCandleContractTest(unittest.TestCase):
    def test_public_pair_and_timeframe_allowlists(self):
        pairs = next(node.value for node in TREE.body
                     if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "_KRAKEN_PAIRS"
                             for target in node.targets))
        intervals = next(node.value for node in TREE.body
                         if isinstance(node, ast.Assign)
                         and any(isinstance(target, ast.Name) and target.id == "_KRAKEN_INTERVALS"
                                 for target in node.targets))
        self.assertEqual(set(ast.literal_eval(pairs)), {
            "BTC/USD", "ETH/USD", "XRP/USD", "SOL/USD", "ADA/USD",
            "DOGE/USD", "HBAR/USD", "XLM/USD", "ICP/USD",
        })
        self.assertEqual(set(ast.literal_eval(intervals)), {
            "1m", "5m", "15m", "30m", "1h", "4h", "1d",
        })

    def test_authenticated_public_endpoint_without_exchange_keys(self):
        fn = next(node for node in TREE.body
                  if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "desktop_market_candles")
        segment = ast.get_source_segment(SOURCE, fn)
        self.assertTrue(any(isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                            and dec.func.attr == "get" and dec.args
                            and isinstance(dec.args[0], ast.Constant)
                            and dec.args[0].value == "/desktop/market-candles"
                            for dec in fn.decorator_list))
        self.assertIn("get_current_user", segment)
        self.assertIn("_KRAKEN_PAIRS[symbol]", segment)
        self.assertIn("_KRAKEN_INTERVALS[timeframe]", segment)
        self.assertIn('"timestamp_unit": "seconds"', segment)
        self.assertNotIn("api_key", segment)
        self.assertNotIn("secret", segment)

    def test_watchlist_uses_completed_public_kraken_hourly_bars(self):
        fn = next(node for node in TREE.body
                  if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "desktop_markets")
        segment = ast.get_source_segment(SOURCE, fn)
        self.assertIn("get_current_user", segment)
        self.assertIn("_fetch_kraken_candles", segment)
        self.assertIn("rows[:-1][-24:]", segment)
        self.assertIn("asyncio.Semaphore(3)", segment)
        self.assertIn('"partial_or_unavailable"', segment)

    def test_upstream_candles_validated(self):
        fn = next(node for node in TREE.body
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "_fetch_kraken_candles")
        segment = ast.get_source_segment(SOURCE, fn)
        self.assertIn("urlopen(request, timeout=10)", segment)
        self.assertIn("isfinite", segment)
        self.assertIn("timestamp <= previous", segment)
        self.assertIn("volume < 0", segment)


if __name__ == "__main__":
    unittest.main()
