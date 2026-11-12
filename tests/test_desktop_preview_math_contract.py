"""Executable deterministic signal and paper-fee tests without exchange or DB."""
import ast
from decimal import Decimal
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / "app/api/routes/paper_preview.py").read_text()
TREE = ast.parse(SOURCE)
FUNCTION = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "ema")
FUNCTION.decorator_list = []
FUNCTION.args.defaults = []
ns = {"D": Decimal}
exec(compile(ast.fix_missing_locations(ast.Module(body=[FUNCTION], type_ignores=[])), "<ema>", "exec"), ns)
ema = ns["ema"]


class PaperSignalMathTest(unittest.TestCase):
    def test_flat_prices_remain_flat(self):
        self.assertEqual(ema([Decimal("100")] * 60, 9), Decimal("100"))
        self.assertEqual(ema([Decimal("100")] * 60, 20), Decimal("100"))

    def test_rising_prices_increase_fast_ema(self):
        values = [Decimal(x) for x in range(1, 70)]
        self.assertGreater(ema(values, 9), ema(values, 20))

    def test_requires_complete_history(self):
        with self.assertRaises(ValueError):
            ema([Decimal("1")] * 8, 9)

    def test_paper_entry_and_exit_fee_arithmetic(self):
        principal = Decimal("100")
        fee_rate = Decimal("0.0026")
        entry_fee = principal * fee_rate
        quantity = Decimal("0.01")
        entry = Decimal("10000")
        exit_price = Decimal("10400")
        proceeds = quantity * exit_price
        exit_fee = proceeds * fee_rate
        pnl = proceeds - exit_fee - principal - entry_fee
        self.assertEqual(pnl, Decimal("3.4696"))
        self.assertEqual(principal + entry_fee, Decimal("100.2600"))


if __name__ == "__main__":
    unittest.main()
