"""Desktop paper bots must be inert, owned, and independent of exchange keys."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app/api/routes/desktop.py").read_text(encoding="utf-8")


class DesktopPaperBotContractTests(unittest.TestCase):
    def test_create_requires_authenticated_owner_and_database(self):
        tree = ast.parse(SOURCE)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_desktop_paper_bot")
        dependencies = {
            n.args[0].id for n in ast.walk(fn.args)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "Depends" and n.args and isinstance(n.args[0], ast.Name)
        }
        self.assertEqual(dependencies, {"get_db", "get_current_user"})

    def test_strategy_wallet_and_bot_queries_are_owner_scoped(self):
        for fragment in (
            "Strategy.user_id == current_user.id",
            "PaperWallet.user_id == current_user.id",
            "DesktopPaperBot.user_id == current_user.id",
            "reserved + payload.allocated_cash",
        ):
            self.assertIn(fragment, SOURCE)

    def test_no_exchange_credentials_or_live_execution_in_create(self):
        tree = ast.parse(SOURCE)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_desktop_paper_bot")
        body = ast.get_source_segment(SOURCE, fn)
        self.assertNotIn("exchange_key", body)
        self.assertNotIn("ccxt", body)
        self.assertIn("is_enabled=False", body)
        self.assertIn('status="configured"', body)

    def test_schema_has_no_exchange_key_field(self):
        source = (ROOT / "app/models/desktop_paper_bot.py").read_text(encoding="utf-8")
        self.assertNotIn("exchange_key_id", source)
        self.assertIn('"nexora_desktop_paper_bots"', source)


if __name__ == "__main__":
    unittest.main()
