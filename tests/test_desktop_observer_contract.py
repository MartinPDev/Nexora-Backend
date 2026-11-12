"""Observer safety: local-only, opt-in, proposal-only, no exchange or auto-approval."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PreviewObserverSafety(unittest.TestCase):
    def test_worker_never_approves_proposals_or_places_orders(self):
        source = (ROOT / "scripts/local_preview_worker.py").read_text()
        tree = ast.parse(source)
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "observer_loop")
        body = ast.get_source_segment(source, fn)
        self.assertIn("await scan(", body)
        self.assertIn("await settle(", body)
        self.assertIn("observer_enabled.is_(True)", body)
        self.assertNotIn("await approve(", body)
        self.assertNotIn("create_order(", body)
        self.assertNotIn("exchange.", body)

    def test_worker_is_guarded_by_local_api_and_explicit_flag(self):
        source = (ROOT / "scripts/local_desktop_api.py").read_text()
        self.assertIn('NEXORA_LOCAL_DESKTOP_API', source)
        self.assertIn('os.getenv("NEXORA_PREVIEW_WORKER") == "YES"', source)
        self.assertIn("asyncio.create_task(observer_loop())", source)
        self.assertIn("task.cancel()", source)

    def test_observer_cannot_be_enabled_without_local_worker(self):
        source = (ROOT / "app/api/routes/paper_preview.py").read_text()
        self.assertIn('os.getenv("NEXORA_PREVIEW_WORKER") != "YES"', source)
        self.assertIn("record.observer_enabled = True", source)
        self.assertIn("record.observer_enabled = False", source)


if __name__ == "__main__":
    unittest.main()
