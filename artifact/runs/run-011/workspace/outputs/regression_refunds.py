"""Regression checks for refund handling, kept outside the protected tests/."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.expense_summary import summarize


class RefundRegressionTests(unittest.TestCase):
    def summarize_rows(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            path.write_text("category,kind,amount\n" + rows, encoding="utf-8")
            return summarize(path)

    def test_refund_reduces_category_balance(self):
        self.assertEqual(
            self.summarize_rows("food,charge,120.00\nfood,refund,20.00\n"),
            {"food": "100.00"},
        )

    def test_refund_only_category_has_negative_two_decimal_balance(self):
        self.assertEqual(
            self.summarize_rows("travel,refund,5.50\n"),
            {"travel": "-5.50"},
        )

    def test_validation_still_rejects_bad_rows(self):
        for row in ["food,charge,-1.00\n", "food,charge,NaN\n",
                    "food,charge,Infinity\n", "food,charge,1.001\n",
                    "food,other,1.00\n", ",charge,1.00\n"]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.summarize_rows(row)

    def test_cli_on_sample_data(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "src" / "expense_summary.py"),
             str(ROOT / "data" / "expenses.csv")],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"books": "12.00", "food": "100.00", "travel": "45.00"})


if __name__ == "__main__":
    unittest.main()
