"""Guard owner scoping and non-execution semantics for desktop bot controls."""
import ast
from pathlib import Path
import unittest

source = (Path(__file__).resolve().parents[1] / "app/api/routes/desktop.py").read_text()
tree = ast.parse(source)

class DesktopBotControlsContract(unittest.TestCase):
    def test_bot_controls_never_start_execution(self):
        for name in ("pause_desktop_paper_bot", "resume_desktop_paper_bot", "delete_desktop_paper_bot"):
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            body = ast.get_source_segment(source, fn)
            self.assertIn("get_current_user", body)
            self.assertIn("_owned_desktop_bot(db, current_user.id, bot_id)", body)
            self.assertNotIn("exchange.create_order", body)
        resume = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "resume_desktop_paper_bot")
        self.assertIn("bot.is_enabled = False", ast.get_source_segment(source, resume))
        self.assertIn('"execution_available": False', ast.get_source_segment(source, resume))

    def test_owner_filter_and_reservation_release(self):
        owner = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_owned_desktop_bot")
        self.assertIn("DesktopPaperBot.user_id == user_id", ast.get_source_segment(source, owner))
        delete = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "delete_desktop_paper_bot")
        self.assertIn("db.delete(bot)", ast.get_source_segment(source, delete))

if __name__ == "__main__":
    unittest.main()
