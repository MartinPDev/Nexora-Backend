"""Contract checks for the v0.3.3 desktop paper wallet.

Run with: python -m unittest tests.test_desktop_wallet_contract
No database or exchange connection is required.
"""
import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES = ROOT / "app" / "api" / "routes" / "desktop.py"


class DesktopWalletContractTest(unittest.TestCase):
    def test_preview_is_read_only_and_account_scoped(self):
        source = ROUTES.read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(
            (node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name == "desktop_paper_preview"),
            None,
        )
        self.assertIsNotNone(fn)
        segment = ast.get_source_segment(source, fn)
        self.assertIn('"/desktop/paper-preview"', segment)
        self.assertIn("get_current_user", segment)
        self.assertIn("DesktopPaperBot.user_id == current_user.id", segment)
        self.assertIn('"available": False', segment)
        self.assertIn('"proposals": []', segment)
        self.assertIn('"positions": []', segment)
        self.assertIn('"trades": []', segment)

    def test_wallet_route_exists_and_is_authenticated(self):
        tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
        fn = next(
            (node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name == "desktop_wallet"),
            None,
        )
        self.assertIsNotNone(fn)
        routes = [
            (dec.func.attr, dec.args[0].value)
            for dec in fn.decorator_list
            if isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.args
            and isinstance(dec.args[0], ast.Constant)
        ]
        self.assertIn(("get", "/desktop/wallet"), routes)
        source = ast.get_source_segment(ROUTES.read_text(encoding="utf-8"), fn)
        self.assertIn("get_current_user", source)
        self.assertIn("PaperWallet", source)
        self.assertIn('"equity": None', source)
        self.assertIn('"pnl": None', source)


if __name__ == "__main__":
    unittest.main()
