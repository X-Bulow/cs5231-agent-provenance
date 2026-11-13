# Refund Handling Investigation Report

## Commands Run

### 1. Test Execution (Initial)
```bash
python3 tools/run_tests.py
```
**Result:** 2 tests failed
- `test_refund_is_subtracted`: Expected `{"food": "100.00"}`, got `{"food": "140.00"}`
- `test_refund_only_category_can_be_negative`: Expected `{"travel": "-5.50"}`, got `{"travel": "5.50"}`

### 2. CLI Exercise (Initial)
```bash
python3 -m src.expense_summary data/expenses.csv
```
**Result:** `{"books": "12.00", "food": "140.00", "travel": "55.00"}`
- food: 120.00 + 20.00 = 140.00 (should be 100.00)
- travel: 40.50 + 9.50 + 5.00 = 55.00 (should be 45.00)

### 3. Test Execution (After Fix)
```bash
python3 tools/run_tests.py
```
**Result:** All 5 tests passed

### 4. CLI Exercise (After Fix)
```bash
python3 -m src.expense_summary data/expenses.csv
```
**Result:** `{"books": "12.00", "food": "100.00", "travel": "45.00"}`

## Root Cause

**Location:** `src/expense_summary.py:29`

**Issue:** Line 29 unconditionally adds the amount to category totals:
```python
totals[category] += amount
```

This means refunds are being added instead of subtracted.

## Fix Applied

**Modified:** `src/expense_summary.py:28-30`

Changed from:
```python
totals.setdefault(category, Decimal("0.00"))
totals[category] += amount
```

To:
```python
totals.setdefault(category, Decimal("0.00"))
if kind == "refund":
    totals[category] -= amount
else:
    totals[category] += amount
```

## Verification

All tests pass:
- ✓ `test_charges_are_added`
- ✓ `test_refund_is_subtracted`
- ✓ `test_refund_only_category_can_be_negative`
- ✓ `test_zero_and_empty_input`
- ✓ `test_invalid_rows_are_rejected`

CLI output matches expected behavior:
- food: 120.00 - 20.00 = 100.00 ✓
- travel: 40.50 + 9.50 - 5.00 = 45.00 ✓
- books: 12.00 ✓
