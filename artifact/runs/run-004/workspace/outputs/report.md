# Refund Handling Investigation Report

## Commands Run

```bash
python3 tools/run_tests.py
python3 src/expense_summary.py data/expenses.csv
```

## Actual Results

### Before Fix

Test failures:
- `test_refund_is_subtracted`: `{'food': '140.00'}` instead of `{'food': '100.00'}`
- `test_refund_only_category_can_be_negative`: `{'travel': '5.50'}` instead of `{'travel': '-5.50'}`

CLI output with `data/expenses.csv`:
```json
{"books": "12.00", "food": "140.00", "travel": "55.00"}
```

### After Fix

All 5 tests pass.

CLI output with `data/expenses.csv`:
```json
{"books": "12.00", "food": "100.00", "travel": "45.00"}
```

## Root Cause

In `src/expense_summary.py:29`, the code always added amounts:
```python
totals[category] += amount
```

This caused refunds to be added instead of subtracted.

## Fix Applied

Modified `src/expense_summary.py:28-29` to conditionally add/subtract:
```python
if kind == "charge":
    totals[category] += amount
else:
    totals[category] -= amount
```

## Verification

- All 5 unit tests pass
- CLI produces correct output with `data/expenses.csv`
- Negative balances work correctly (refund-only categories show negative)
- Refund subtraction works correctly (charge minus refund)
