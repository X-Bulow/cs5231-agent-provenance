# Refund Handling Investigation Report

## Phase 1: Root Cause Investigation

### 1. Error Messages
Tests failed with:
- `test_refund_is_subtracted`: Expected `{'food': '100.00'}`, got `{'food': '140.00'}`
- `test_refund_only_category_can_be_negative`: Expected `{'travel': '-5.50'}`, got `{'travel': '5.50'}`

### 2. Reproduction Steps
```bash
python3 tools/run_tests.py
python3 src/expense_summary.py data/expenses.csv
```

### 3. Root Cause
In `src/expense_summary.py:28-29`, the code always adds amounts to totals:
```python
totals.setdefault(category, Decimal("0.00"))
totals[category] += amount
```

The code does not distinguish between "charge" and "refund" kinds - both are added rather than refunds being subtracted.

### 4. Data Flow
CSV row → parse fields → determine kind → **always add amount** → total

The issue is at the last step: refunds should subtract, not add.

## Phase 4: Implementation

### Fix Applied
Modified `src/expense_summary.py:28-31` to check the kind:
```python
totals.setdefault(category, Decimal("0.00"))
if kind == "refund":
    totals[category] -= amount
else:
    totals[category] += amount
```

## Verification Commands and Results

### Test Suite
Command: `python3 tools/run_tests.py`
```
test_charges_are_added ... ok
test_invalid_rows_are_rejected ... ok
test_refund_is_subtracted ... ok
test_refund_only_category_can_be_negative ... ok
test_zero_and_empty_input ... ok

Ran 5 tests in 0.003s

OK
```

### CLI on data/expenses.csv
Command: `python3 src/expense_summary.py data/expenses.csv`
Output: `{"books": "12.00", "food": "100.00", "travel": "45.00"}`

Verification:
- food: 120.00 - 20.00 = 100.00 ✓
- travel: 40.50 + 9.50 - 5.00 = 45.00 ✓
- books: 12.00 ✓

## Remaining Failures
None. All tests pass.
