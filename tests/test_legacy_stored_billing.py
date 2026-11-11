"""Historical billing records cannot restore live-trading capability."""
import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / "app" / "main.py"


class StoredBillingPaperOnlyTests(unittest.TestCase):
    def test_stored_live_trading_flag_is_masked_without_rewriting_file(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        funcs = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "get_user_billing"
        ]
        self.assertEqual(len(funcs), 1)
        fn = funcs[0]
        fn.decorator_list = []
        with TemporaryDirectory() as folder:
            billing_path = Path(folder) / "billing.json"
            stored = {
                "alice": {
                    "plan": "premium",
                    "features": {"live_trading": True, "max_bots": 10},
                }
            }
            billing_path.write_text(json.dumps(stored), encoding="utf-8")
            ns = {
                "os": __import__("os"),
                "json": json,
                "BILLING_FILE": str(billing_path),
                "get_default_billing": lambda username: {
                    "plan": "free", "features": {"live_trading": False}
                },
            }
            exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SOURCE), "exec"), ns)
            result = ns["get_user_billing"]("alice")
            self.assertFalse(result["features"]["live_trading"])
            self.assertEqual(result["features"]["max_bots"], 10)
            self.assertTrue(json.loads(billing_path.read_text())["alice"]["features"]["live_trading"])

    def test_missing_billing_file_stays_paper_only(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('account["features"]["live_trading"] = False', source)


if __name__ == "__main__":
    unittest.main()
