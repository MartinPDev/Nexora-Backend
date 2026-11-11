"""All legacy subscription tiers must remain paper-only in beta."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "app" / "main.py"


class PaperOnlyEntitlementsTests(unittest.TestCase):
    def test_paid_tiers_cannot_enable_live_trading(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "activate_user_plan"
        ]
        self.assertEqual(len(matches), 1)
        fn = matches[0]
        assignments = [
            node for node in fn.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "plans" for target in node.targets)
        ]
        self.assertEqual(len(assignments), 1)
        plans = ast.literal_eval(assignments[0].value)
        self.assertEqual(set(plans), {"basic", "pro", "premium"})
        for name, features in plans.items():
            with self.subTest(plan=name):
                self.assertTrue(features["paper_trading"])
                self.assertFalse(features["live_trading"])


if __name__ == "__main__":
    unittest.main()
