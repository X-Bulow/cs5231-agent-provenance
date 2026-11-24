# Investigation Report: Refund Handling Bug

## Commands Executed

### Test Reproduction
```bash
python3 tools/run_tests.py
```

**Initial Results (before fix):**
```
test_refund_is_subtracted ... FAIL
  Expected: {'food': '100.00'}, Got: {'food': '140.00'}
test_refund_only_category_can_be_negative ... FAIL
  Expected: {'travel': '-5.50'}, Got: {'travel': '5.50'}
```

### CLI Exercise
```bash
python3 src/expense_summary.py data/expenses.csv
```

**Initial Result (before fix):**
```json
{"books": "12.00", "food": "140.00", "travel": "55.00"}
```

**Expected Result:**
- food: 120.00 - 20.00 = 100.00 ✓ (after fix)
- travel: 40.50 + 9.50 - 5.00 = 45.00 ✓ (after fix)
- books: 12.00 ✓

## Root Cause

In `src/expense_summary.py:29`, both charges and refunds were being added to the category balance:
```python
totals[category] += amount  # Wrong: adds for both charge and refund
```

## Fix Applied

Modified the logic to differentiate between charges and refunds:
```python
if kind == "charge":
    totals[category] += amount
else:
    totals[category] -= amount
```

## Final Verification

**Tests (after fix):**
```
Ran 5 tests in 0.005s
OK
```

**CLI (after fix):**
```json
{"books": "12.00", "food": "100.00", "travel": "45.00"}
```

All tests pass. Refund handling now correctly subtracts from category balances.
