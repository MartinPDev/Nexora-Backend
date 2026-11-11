"""Schema scripts must require opt-in and offer a read-only preflight."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scripts"


class SchemaSafetyTests(unittest.TestCase):
    def test_migrations_require_explicit_opt_in(self):
        for name in ("create_paper_wallet_table.py", "create_desktop_paper_bot_table.py"):
            with self.subTest(script=name):
                source = (ROOT / name).read_text(encoding="utf-8")
                ast.parse(source)
                self.assertIn('os.getenv("NEXORA_CONFIRM_SCHEMA_CREATE") != "YES"', source)
                self.assertIn("Schema creation blocked", source)

    def test_preflight_does_not_write_database(self):
        source = (ROOT / "check_paper_schema.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertIn("get_table_names()", source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, {"create", "create_all", "drop", "drop_all", "execute", "commit", "add"})


if __name__ == "__main__":
    unittest.main()
