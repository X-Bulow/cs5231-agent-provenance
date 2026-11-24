# Refund Handling Bug Report

## Commands Executed

### Reproduction Command
```bash
python3 tools/run_tests.py
```

### Actual Results (Before Fix)
```
test_charges_are_added (test_expense_summary.ExpenseSummaryTests) ... ok
test_invalid_rows_are_rejected (test_expense_summary.ExpenseSummaryTests) ... ok
test_refund_is_subtracted (test_expense_summary.ExpenseSummaryTests) ... FAIL
test_refund_only_category_can_be_negative (test_expense_summary.ExpenseSummaryTests) ... FAIL
test_zero_and_empty_input (test_expense_summary.ExpenseSummaryTests) ... ok

======================================================================
FAIL: test_refund_is_subtracted
----------------------------------------------------------------------
AssertionError: {'food': '140.00'} != {'food': '100.00'}
- {'food': '140.00'}
?            ^
+ {'food': '100.00'}

======================================================================
FAIL: test_refund_only_category_can_be_negative
----------------------------------------------------------------------
AssertionError: {'travel': '5.50'} != {'travel': '-5.50'}
- {'travel': '5.50'}
+ {'travel': '-5.50'}
```

### CLI Test Command
```bash
python3 src/expense_summary.py data/expenses.csv
```

### Actual CLI Output (Before Fix)
```json
{"books": "12.00", "food": "140.00", "travel": "55.00"}
```

## Root Cause

**Location:** `src/expense_summary.py:29`

**Problem:** The code always adds the amount to the category balance:
```python
totals[category] += amount
```

The `kind` field ("charge" or "refund") is validated but never used to determine whether to add or subtract.

## Fix Applied

Modified `src/expense_summary.py:28-30` to check the `kind` field:
```python
if kind == "charge":
    totals[category] += amount
else:
    totals[category] -= amount
```

## Verification Results (After Fix)

### Test Output
```
test_charges_are_added (test_expense_summary.ExpenseSummaryTests) ... ok
test_invalid_rows_are_rejected (test_expense_summary.ExpenseSummaryTests) ... ok
test_refund_is_subtracted (test_expense_summary.ExpenseSummaryTests) ... ok
test_refund_only_category_can_be_negative (test_expense_summary.ExpenseSummaryTests) ... ok
test_zero_and_empty_input (test_expense_summary.ExpenseSummaryTests) ... ok

----------------------------------------------------------------------
Ran 5 tests in 0.004s

OK
```

### CLI Output
```json
{"books": "12.00", "food": "100.00", "travel": "45.00"}
```

### Manual Verification of expenses.csv
- food: 120.00 (charge) - 20.00 (refund) = 100.00 ✓
- travel: 40.50 (charge) + 9.50 (charge) - 5.00 (refund) = 45.00 ✓
- books: 12.00 (charge) = 12.00 ✓

## Remaining Failures

None. All tests pass.
