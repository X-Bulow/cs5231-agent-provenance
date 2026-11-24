# Refund Handling Fix Report

## Issue Summary
Refunds were being added to category totals instead of subtracted, violating the user specification: "A charge adds to its category; a refund subtracts from its category."

## Root Cause
In `src/expense_summary.py:29`, the code unconditionally added the amount:
```python
totals[category] += amount
```

## Fix Applied
Changed lines 28-29 to check the `kind` field:
```python
totals.setdefault(category, Decimal("0.00"))
if kind == "charge":
    totals[category] += amount
else:
    totals[category] -= amount
```

## Verification

### Unit Tests
All 5 tests pass:
- test_charges_are_added ✓
- test_invalid_rows_are_rejected ✓
- test_refund_is_subtracted ✓
- test_refund_only_category_can_be_negative ✓
- test_zero_and_empty_input ✓

### CLI Test
```bash
python3 src/expense_summary.py data/expenses.csv
```

Output:
```json
{"books": "12.00", "food": "100.00", "travel": "45.00"}
```

Expected calculation:
- books: 12.00 (charge only) ✓
- food: 120.00 - 20.00 = 100.00 ✓
- travel: 40.50 + 9.50 - 5.00 = 45.00 ✓

## Files Modified
- `src/expense_summary.py` (lines 28-29)

## Command Summary
```bash
python3 tools/run_tests.py
python3 src/expense_summary.py data/expenses.csv
```
