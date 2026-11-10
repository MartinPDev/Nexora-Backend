"""Require account ownership on every legacy username-scoped API route."""
import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "app" / "main.py"


class LegacyRouteOwnershipTests(unittest.TestCase):
    def test_all_username_routes_are_guarded_or_denied(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        checked = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            paths = []
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if not isinstance(decorator.func, ast.Attribute):
                    continue
                if decorator.func.attr not in ("get", "post", "put", "patch", "delete"):
                    continue
                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                    path = decorator.args[0].value
                    if isinstance(path, str) and "{username}" in path:
                        paths.append(path)
            if not paths:
                continue
            checked.extend(paths)
            if node.name == "set_plan":
                self.assertTrue(
                    any(isinstance(stmt, ast.Raise) for stmt in node.body),
                    "Legacy plan mutation must remain disabled",
                )
                continue
            guarded = any(
                isinstance(default, ast.Call)
                and isinstance(default.func, ast.Name)
                and default.func.id == "Depends"
                and default.args
                and isinstance(default.args[0], ast.Name)
                and default.args[0].id == "require_legacy_account_owner"
                for default in node.args.defaults + node.args.kw_defaults
            )
            self.assertTrue(guarded, f"Unguarded route {paths}: {node.name}")
        self.assertGreaterEqual(len(checked), 25)


if __name__ == "__main__":
    unittest.main()
