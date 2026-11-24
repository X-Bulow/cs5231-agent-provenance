# Refund Handling Investigation Report

## Commands Executed

### Test Reproduction
```bash
python3 tools/run_tests.py
```

**Initial Results (Failures):**
- `test_refund_is_subtracted`: Expected `{"food": "100.00"}`, got `{"food": "140.00"}`
- `test_refund_only_category_can_be_negative`: Expected `{"travel": "-5.50"}`, got `{"travel": "5.50"}`

### CLI Exercise
```bash
python3 src/expense_summary.py data/expenses.csv
```

**Initial Result:** `{"books": "12.00", "food": "140.00", "travel": "55.00"}`

## Root Cause

In `src/expense_summary.py:29`, the code always **added** the amount to the category total:

```python
totals[category] += amount
```

The `kind` field ("charge" or "refund") was validated but never used to determine whether to add or subtract.

## Fix Applied

Modified lines 28-29 to conditionally add or subtract based on `kind`:

```python
totals.setdefault(category, Decimal("0.00"))
if kind == "charge":
    totals[category] += amount
else:
    totals[category] -= amount
```

## Verification Results

### After Fix - Tests
```bash
python3 tools/run_tests.py
```

**Result:** All 5 tests pass ✓

### After Fix - CLI
```bash
python3 src/expense_summary.py data/expenses.csv
```

**Result:** `{"books": "12.00", "food": "100.00", "travel": "45.00"}`

**Verification:**
- food: 120.00 - 20.00 = 100.00 ✓
- travel: 40.50 + 9.50 - 5.00 = 45.00 ✓
- books: 12.00 ✓

## Conclusion

The refund handling is now fixed. Refunds correctly subtract from category balances, and categories with only refunds can have negative balances as specified.
