"""Guard local desktop API startup from trading engine imports and remote binding."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/local_desktop_api.py"


class LocalDesktopApiTests(unittest.TestCase):
    def test_no_legacy_app_or_worker_imports(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
        self.assertNotIn("app.main", imports)
        self.assertFalse(any("supervisor" in name or "asset_bot_engine" in name for name in imports))
        self.assertIn("app.api.routes", imports)

    def test_opt_in_and_local_database_guard(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('NEXORA_LOCAL_DESKTOP_API', source)
        self.assertIn('db.host not in {"127.0.0.1", "localhost"}', source)
        self.assertIn('db.database != "cryptobot"', source)
        self.assertIn('settings.app_env.lower() in {"production", "prod"}', source)


if __name__ == "__main__":
    unittest.main()
