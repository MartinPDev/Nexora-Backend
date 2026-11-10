"""Regression checks for the legacy billing entitlement route (no app boot required)."""
import ast
import unittest
from pathlib import Path


class LegacyBillingSecurityTests(unittest.TestCase):
    def test_public_plan_upgrade_is_denied(self):
        source = Path(__file__).resolve().parents[1] / "app" / "main.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        functions = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "set_plan"
        ]
        self.assertEqual(len(functions), 1)
        func = functions[0]
        self.assertEqual(len(func.body), 2)
        denial = func.body[1]
        self.assertIsInstance(denial, ast.Raise)
        call = denial.exc
        self.assertIsInstance(call, ast.Call)
        self.assertIsInstance(call.func, ast.Name)
        self.assertEqual(call.func.id, "HTTPException")
        self.assertTrue(any(
            kw.arg == "status_code"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == 403
            for kw in call.keywords
        ))


if __name__ == "__main__":
    unittest.main()
