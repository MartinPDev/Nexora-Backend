"""Desktop API route contract and account ownership regressions."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "app" / "api" / "routes" / "desktop.py"
MAIN = ROOT / "app" / "main.py"


class DesktopApiContractTests(unittest.TestCase):
    def test_desktop_router_mounted(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertIn("app.include_router(desktop_router, prefix=\"/api/v1\")", source)

    def test_expected_read_routes_present(self):
        tree = ast.parse(DESKTOP.read_text(encoding="utf-8"))
        paths = {}
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            for dec in fn.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr == "get" and dec.args and isinstance(dec.args[0], ast.Constant):
                        paths[dec.args[0].value] = fn
        self.assertTrue({"/health", "/desktop/bots", "/desktop/strategies", "/desktop/dashboard", "/desktop/portfolio", "/desktop/trades", "/desktop/notifications", "/desktop/markets"}.issubset(paths))
        for path in ("/desktop/bots", "/desktop/strategies", "/desktop/dashboard", "/desktop/portfolio", "/desktop/trades", "/desktop/notifications", "/desktop/markets"):
            fn = paths[path]
            names = [
                n.args[0].id
                for n in ast.walk(fn.args)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "Depends"
                and n.args and isinstance(n.args[0], ast.Name)
            ]
            self.assertIn("get_current_user", names, path)
            if path in {"/desktop/bots", "/desktop/strategies", "/desktop/dashboard", "/desktop/trades", "/desktop/portfolio"}:
                self.assertIn("get_db", names, path)

    def test_queries_filter_by_current_user(self):
        source = DESKTOP.read_text(encoding="utf-8")
        self.assertIn("Bot.user_id == current_user.id", source)
        self.assertIn("Strategy.user_id == current_user.id", source)
        self.assertIn("RapidScalperTrade.username == current_user.username", source)
        self.assertIn('RapidScalperTrade.status == "paper_executed"', source)
        self.assertIn("RapidScalperTrade.closed_at.isnot(None)", source)
        self.assertIn("PaperWallet.user_id == current_user.id", source)
        self.assertIn('"paper_cash": float(wallet.cash_balance) if wallet else None', source)
        self.assertIn('"portfolio_value": None', source)
        self.assertIn('Decimal("1000.00")', source)
        self.assertIn("with db.begin_nested()", source)
        self.assertIn('"financial_data_status": "unavailable"', source)
        self.assertIn('"portfolio_value": None', source)


if __name__ == "__main__":
    unittest.main()
