# Refund Handling Investigation Report

## Commands Executed

### Test Reproduction
```bash
python3 tools/run_tests.py
```
**Result:** 2 tests failed:
- `test_refund_is_subtracted`: expected `{'food': '100.00'}`, got `{'food': '140.00'}`
- `test_refund_only_category_can_be_negative`: expected `{'travel': '-5.50'}`, got `{'travel': '5.50'}`

### CLI Exercise
```bash
python3 src/expense_summary.py data/expenses.csv
```
**Original Result:** `{"books": "12.00", "food": "140.00", "travel": "55.00"}`

## Root Cause

**Location:** `src/expense_summary.py:29`

**Issue:** Line 29 unconditionally added amounts to totals:
```python
totals[category] += amount
```

This caused refunds to be added instead of subtracted.

## Fix Applied

Modified `src/expense_summary.py:28-30` to check the kind field:

```python
totals.setdefault(category, Decimal("0.00"))
if kind == "refund":
    totals[category] -= amount
else:
    totals[category] += amount
```

## Verification Results

### Tests
```bash
python3 tools/run_tests.py
```
**Result:** All 5 tests pass

### CLI
```bash
python3 src/expense_summary.py data/expenses.csv
```
**Result:** `{"books": "12.00", "food": "100.00", "travel": "45.00"}`

**Expected calculations:**
- food: 120.00 - 20.00 = 100.00 ✓
- travel: 40.50 + 9.50 - 5.00 = 45.00 ✓
- books: 12.00 ✓

## Remaining Failures

None.
