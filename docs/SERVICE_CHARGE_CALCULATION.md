# Service Charge Calculation Order

This document defines the calculation order used by the Service Charge module.
All screens, saves, reloads, reports, slips, cash preparation, and JV reports must
use the same order so totals do not drift between views.

## Per-Employee Calculation

Gross Service:

```text
Gross Service = Service Rate x Service Weight
```

Deductions are calculated in this order:

1. Sick Deduction
2. Leave Day Deduction
3. Leave Hour Deduction
4. Late Deduction
5. Evaluation Deduction

Total Raw Deduction:

```text
Total Raw Deduction =
  Sick Deduction
  + Leave Day Deduction
  + Leave Hour Deduction
  + Late Deduction
  + Evaluation Deduction
```

Applied Deduction:

```text
Applied Deduction = min(Total Raw Deduction, Gross Service)
```

Total After Deduction:

```text
Total After Deduction = Gross Service - Applied Deduction
```

Net Service:

```text
Net Service = Total After Deduction - Deposit Deduction + Deposit Refund
```

The current system has no deposit refund entry in ServiceEmployee, so report
serializers use `0` for Deposit Refund until that feature is added.

## Safety Rules

- Total After Deduction must never be negative.
- Net Service must never be negative.
- If Total After Deduction is `0`, Deposit Deduction must be `0`.
- Deposit Deduction must not make Net Service negative.
- If Total Raw Deduction is greater than Gross Service, Applied Deduction is
  capped at Gross Service and the remark must include:

```text
Deduction capped at service amount
```

## Report Summary Rules

- Service Summary Actual Employee Paid = `SUM(Total After Deduction)`
- Cash Preparation Grand Total = `SUM(Net Service)`
- Monthly JV Department Debit = `SUM(Total After Deduction)` grouped by JV
  department code
- Service Detail Report displayed Income Amount = `Total After Deduction`
  because the printed report must show the amount actually paid, not the gross
  service amount before deductions.

## Shared Helpers

Backend code should use:

- `calculate_service_amounts(row)`
- `service_row_total_after_deduction(row)`

Frontend preview/recalculate code mirrors the same logic in:

- `recalculate_service_rows(rows, service_rate)`
- `service_row_total_after_deduction(row)`

Do not add independent formulas inside reports. When a new report needs Service
Charge totals, call the shared helper or serialize from an object that already
used the shared helper.
