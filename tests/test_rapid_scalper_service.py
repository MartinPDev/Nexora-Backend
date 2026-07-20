import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.rapid_scalper_service import (
    TOTAL_COST_RATE,
    open_paper_trade,
    paper_pnl,
    remaining_seconds,
    update_and_maybe_close,
)


def make_trade(side="buy", target=0.5, mode="conservative"):
    return SimpleNamespace(
        side=side,
        scalp_target_percent=target,
        mode=mode,
        amount_usd=100.0,
        status="preview_ready",
        entry_price=None,
        current_price=None,
        target_price=None,
        stop_price=None,
        stop_percent=None,
        expires_at=None,
        last_price_at=None,
        data_quality=None,
        gross_pnl_usd=None,
        gross_pnl_percent=None,
        estimated_cost_usd=None,
        pnl_usd=None,
        pnl_percent=None,
        exit_price=None,
        exit_reason=None,
        closed_at=None,
    )


class RapidScalperServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, 12, 0, 0)

    def test_open_trade_stays_running_and_does_not_manufacture_exit(self):
        trade = open_paper_trade(make_trade(), 100.0, self.now)
        self.assertEqual(trade.status, "paper_running")
        self.assertIsNone(trade.exit_price)
        self.assertIsNone(trade.closed_at)
        self.assertEqual(remaining_seconds(trade, self.now), 45)

    def test_costs_are_deducted_from_paper_result(self):
        result = paper_pnl(100.0, 100.5, "buy", 100.0)
        self.assertAlmostEqual(result["gross_pnl_usd"], 0.5)
        self.assertAlmostEqual(result["estimated_cost_usd"], 100 * TOTAL_COST_RATE)
        self.assertLess(result["net_pnl_usd"], result["gross_pnl_usd"])

    def test_target_closes_at_observed_price(self):
        trade = open_paper_trade(make_trade(), 100.0, self.now)
        update_and_maybe_close(trade, 100.6, self.now + timedelta(seconds=10))
        self.assertEqual(trade.status, "paper_closed")
        self.assertEqual(trade.exit_reason, "TARGET_REACHED")
        self.assertEqual(trade.exit_price, 100.6)

    def test_protective_boundary_closes_first(self):
        trade = open_paper_trade(make_trade(), 100.0, self.now)
        update_and_maybe_close(trade, 99.6, self.now + timedelta(seconds=5))
        self.assertEqual(trade.exit_reason, "PROTECTIVE_STOP")

    def test_maximum_duration_uses_observed_price(self):
        trade = open_paper_trade(make_trade(), 100.0, self.now)
        update_and_maybe_close(trade, 100.1, self.now + timedelta(seconds=45))
        self.assertEqual(trade.exit_reason, "MAX_DURATION")
        self.assertEqual(trade.exit_price, 100.1)

    def test_sell_direction_profit_is_calculated_correctly(self):
        result = paper_pnl(100.0, 99.0, "sell", 100.0)
        self.assertAlmostEqual(result["gross_pnl_percent"], 1.0)


if __name__ == "__main__":
    unittest.main()
