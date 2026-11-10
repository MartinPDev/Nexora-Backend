"""Regression tests for account-owned legacy billing endpoints."""
import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "app" / "main.py"


class FakeHTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code


def load_guard():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    matching = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "require_legacy_account_owner"
    ]
    if len(matching) != 1:
        raise AssertionError("Missing unique ownership guard")
    namespace = {
        "Header": lambda value=None: value,
        "HTTPException": FakeHTTPException,
        "SESSIONS": {"valid-session": "alice"},
    }
    exec(compile(ast.Module(body=matching, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["require_legacy_account_owner"]


class LegacyBillingOwnershipTests(unittest.TestCase):
    def test_correct_owner_allowed(self):
        self.assertEqual(load_guard()("alice", "valid-session"), "alice")

    def test_missing_session_denied(self):
        with self.assertRaises(FakeHTTPException) as caught:
            load_guard()("alice", None)
        self.assertEqual(caught.exception.status_code, 401)

    def test_other_user_denied(self):
        with self.assertRaises(FakeHTTPException) as caught:
            load_guard()("bob", "valid-session")
        self.assertEqual(caught.exception.status_code, 403)

    def test_billing_routes_require_guard(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        expected = {
            "get_billing",
            "create_checkout_session",
            "create_basic_checkout",
            "checkout_pro",
            "checkout_premium",
        }
        functions = {
            node.name: node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in expected
        }
        self.assertEqual(set(functions), expected)
        for name, func in functions.items():
            dependencies = [
                node for node in ast.walk(func.args)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Depends"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "require_legacy_account_owner"
            ]
            self.assertTrue(dependencies, f"{name} missing account owner guard")


if __name__ == "__main__":
    unittest.main()
