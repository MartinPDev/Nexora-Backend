"""Test configured Stripe checkout return URLs without importing the app."""
import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace


SOURCE = Path(__file__).resolve().parents[1] / "app" / "main.py"


class HTTPError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


def helper(env="production"):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "legacy_checkout_return_url"]
    if len(funcs) != 1:
        raise AssertionError("Checkout origin helper missing")
    ns = {"os": os, "settings": SimpleNamespace(app_env=env), "HTTPException": HTTPError}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns["legacy_checkout_return_url"]


class CheckoutReturnOriginTests(unittest.TestCase):
    def test_production_requires_origin(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPError) as e:
                helper()("alice")
        self.assertEqual(e.exception.status_code, 503)

    def test_production_https_origin(self):
        with patch.dict(os.environ, {"NEXORA_PUBLIC_APP_ORIGIN": "https://beta.nexorabot.ca"}):
            self.assertEqual(helper()("alice"), "https://beta.nexorabot.ca/dashboard-ui/alice")

    def test_production_rejects_http(self):
        with patch.dict(os.environ, {"NEXORA_PUBLIC_APP_ORIGIN": "http://127.0.0.1:8000"}):
            with self.assertRaises(HTTPError):
                helper()("alice")

    def test_rejects_external_path(self):
        with patch.dict(os.environ, {"NEXORA_PUBLIC_APP_ORIGIN": "https://beta.nexorabot.ca/evil"}):
            with self.assertRaises(HTTPError):
                helper()("alice")

    def test_encodes_username(self):
        with patch.dict(os.environ, {"NEXORA_PUBLIC_APP_ORIGIN": "https://beta.nexorabot.ca"}):
            self.assertTrue(helper()("alice/bob").endswith("/alice%2Fbob"))

    def test_development_localhost_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(helper("development")("alice"), "http://127.0.0.1:8000/dashboard-ui/alice")

    def test_all_checkout_routes_use_helper(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        names = {"create_checkout_session", "create_basic_checkout", "checkout_pro", "checkout_premium"}
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual(len(funcs), 4)
        for fn in funcs:
            calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "legacy_checkout_return_url"]
            self.assertEqual(len(calls), 2, fn.name)


if __name__ == "__main__":
    unittest.main()
