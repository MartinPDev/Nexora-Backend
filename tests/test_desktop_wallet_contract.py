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
    def test_preview_is_persisted_and_owner_scoped(self):
        source = (ROOT / "app" / "api" / "routes" / "paper_preview.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "read_preview")
        self.assertTrue(any(isinstance(dec, ast.Call) and dec.args
                            and isinstance(dec.args[0], ast.Constant)
                            and dec.args[0].value == "/desktop/paper-preview"
                            for dec in fn.decorator_list))
        body = ast.get_source_segment(source, fn)
        self.assertIn("get_current_user", body)
        self.assertIn("PaperPreviewProposal.user_id == user.id", body)
        self.assertIn("PaperPreviewPosition.user_id == user.id", body)
        self.assertIn('"available": True', body)

    def test_settled_preview_trades_appear_in_owner_scoped_history(self):
        source = ROUTES.read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "desktop_trades")
        segment = ast.get_source_segment(source, fn)
        self.assertIn("PaperPreviewPosition.user_id == current_user.id", segment)
        self.assertIn('PaperPreviewPosition.status == "CLOSED"', segment)
        self.assertIn('"source": "paper_preview"', segment)
        self.assertIn('"source": "rapid_scalper_paper"', segment)
        self.assertIn("reverse=True", segment)

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
        self.assertIn('"open_positions": len(portfolio["positions"])', source)


if __name__ == "__main__":
    unittest.main()
