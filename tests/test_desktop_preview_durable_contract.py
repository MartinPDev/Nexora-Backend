"""Contract checks for durable, approval-only paper preview (offline)."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTE = (ROOT / "app/api/routes/paper_preview.py").read_text()
TREE = ast.parse(ROUTE)


def body(name):
    fn = next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(ROUTE, fn)


class DurablePreviewContract(unittest.TestCase):
    def test_approval_is_owner_scoped_locked_and_exactly_once(self):
        s = body("approve")
        for required in ("with_for_update()", "PaperPreviewProposal.user_id == user.id",
                         "PaperPreviewPosition", 'proposal.status = "APPROVED"',
                         "payload.payload_hash != proposal.payload_hash",
                         "proposal.expires_at <= datetime.utcnow()", "db.commit()"):
            self.assertIn(required, s)
        self.assertNotIn("create_order", s)

    def test_scan_uses_completed_kraken_candles_and_crossover(self):
        s = body("scan")
        for required in ("rows[:-1]", "_fetch_kraken_candles", "previous_fast <= previous_slow",
                         "fast > slow", "candle feed is stale", "sha256", "PaperPreviewProposal", "timedelta(minutes=5)"):
            self.assertIn(required, s)

    def test_settlement_locks_wallet_and_position_and_uses_fees(self):
        s = body("settle")
        for required in ("with_for_update()", "rows[:-1]", "STOP_OR_TRAIL",
                         "TAKE_PROFIT", "MAX_HOLD", 'min(stop, D(str(candle["open"])))', "exit_fee", "wallet.cash_balance",
                         'position.status = "CLOSED"', "db.commit()"):
            self.assertIn(required, s)

    def test_model_uniqueness_and_explicit_migration(self):
        model = (ROOT / "app/models/paper_preview.py").read_text()
        migration = (ROOT / "scripts/sql/preview_paper_v1.sql").read_text()
        self.assertIn('UniqueConstraint("bot_id", "candle_timestamp"', model)
        self.assertIn("proposal_id: Mapped[str]", model)
        self.assertIn("uq_preview_open_bot", migration)
        self.assertIn("BEGIN;", migration)
        self.assertIn("COMMIT;", migration)

    def test_local_api_mounts_preview_without_trading_worker(self):
        s = (ROOT / "scripts/local_desktop_api.py").read_text()
        self.assertIn("paper_preview.router", s)
        self.assertNotIn("app.main", s.replace("Does not import app.main", ""))


if __name__ == "__main__":
    unittest.main()
