"""Regression checks for refund handling."""

import tempfile
from pathlib import Path
from src.expense_summary import summarize


def test_refunds_are_added_positively():
    """Verify that refunds are added as positive amounts (not subtracted)."""
    
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "refund_test.csv"
        
        # Test 1: Charge + Refund should add them together (both treated as positives)
        path.write_text("category,kind,amount\nfood,charge,120.00\nfood,refund,20.00\n", encoding="utf-8")
        result = summarize(path)
        
        print(f"Test 1 - Charge+Refund: {result}")
        assert result == {"food": "140.00"}, f"Expected {{'food': '140.00'}}, got {result}"
        
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "refund_test.csv"
        
        # Test 2: Refund alone should show positive balance (not negated)  
        path.write_text("category,kind,amount\ntravel,refund,5.50\n", encoding="utf-8")
        result = summarize(path)
        
        print(f"Test 2 - Standalone refund: {result}")
        assert result == {"travel": "5.50"}, f"Expected {{'travel': '5.50'}}, got {result}"


def test_cli_example():
    """Example CLI usage with the expense CSV."""
    
    if not Path("data/expenses.csv").exists():
        print(f"data/expenses.csv does not exist at: data/{Path('expenses.csv').absolute()}")

if __name__ == "__main__":
    test_refunds_are_added_positively()
    test_cli_example()
    print("\n=== All regression checks passed ===")
