"""Prevent legacy dashboard regressions during authorization migration."""
import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "app" / "main.py"


class LegacyDashboardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def function(self, name):
        matches = [n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_dashboard_shell_allows_browser_navigation(self):
        fn = self.function("dashboard_ui")
        self.assertFalse(any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "require_legacy_account_owner"
            for n in ast.walk(fn.args)
        ))

    def test_dashboard_attaches_session_token_to_api_calls(self):
        fn = self.function("dashboard_ui")
        body = ast.get_source_segment(self.source, fn)
        self.assertIn('headers.set("x-session-token", savedToken)', body)
        self.assertIn('resolved.origin !== window.location.origin', body)

    def test_plan_upgrades_use_checkout_not_direct_entitlement(self):
        fn = self.function("dashboard_ui")
        body = ast.get_source_segment(self.source, fn)
        self.assertIn("checkoutPlan", body)
        self.assertIn("'/billing/{username}/checkout/' + checkoutPlan", body)
        self.assertNotIn("'/billing/{username}/set-plan/' + plan", body)

    def test_dashboard_data_routes_remain_guarded(self):
        fn = self.function("get_dashboard")
        self.assertTrue(any(
            isinstance(n, ast.Name) and n.id == "require_legacy_account_owner"
            for n in ast.walk(fn.args)
        ))


if __name__ == "__main__":
    unittest.main()
