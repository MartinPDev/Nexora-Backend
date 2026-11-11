"""Regression checks for account-scoped wallet reservations and quiet SQL logging."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PrivacyAndAccountingTests(unittest.TestCase):
    def test_sql_parameter_echo_disabled(self):
        source = (ROOT / "app/core/database.py").read_text(encoding="utf-8")
        self.assertIn("echo=False", source)
        self.assertNotIn("echo=True", source)

    def test_dashboard_counts_only_inert_desktop_paper_bots(self):
        source = (ROOT / "app/api/routes/desktop.py").read_text(encoding="utf-8")
        start = source.index("def desktop_dashboard(")
        end = source.index('@router.get("/desktop/portfolio")', start)
        dashboard = source[start:end]
        self.assertIn("DesktopPaperBot.user_id == current_user.id", dashboard)
        self.assertIn('"bots_running": 0', dashboard)
        self.assertNotIn("db.query(Bot)", dashboard)

    def test_wallet_reservations_are_user_scoped(self):
        source = (ROOT / "app/api/routes/desktop.py").read_text(encoding="utf-8")
        self.assertIn("DesktopPaperBot.user_id == current_user.id", source)
        self.assertIn('"reserved_cash": float(reserved)', source)
        self.assertIn('"paper_cash_balance": float(wallet.cash_balance)', source)
        self.assertIn('"total_value": None', source)


if __name__ == "__main__":
    unittest.main()
