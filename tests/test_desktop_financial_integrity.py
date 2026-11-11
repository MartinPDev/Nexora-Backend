"""Regression checks for account-scoped wallet reservations and quiet SQL logging."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PrivacyAndAccountingTests(unittest.TestCase):
    def test_sql_parameter_echo_disabled(self):
        source = (ROOT / "app/core/database.py").read_text(encoding="utf-8")
        self.assertIn("echo=False", source)
        self.assertNotIn("echo=True", source)

    def test_wallet_reservations_are_user_scoped(self):
        source = (ROOT / "app/api/routes/desktop.py").read_text(encoding="utf-8")
        self.assertIn("DesktopPaperBot.user_id == current_user.id", source)
        self.assertIn('"reserved_cash": float(reserved)', source)
        self.assertIn('"paper_cash_balance": float(wallet.cash_balance)', source)
        self.assertIn('"total_value": None', source)


if __name__ == "__main__":
    unittest.main()
