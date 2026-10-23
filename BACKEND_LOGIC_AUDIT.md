# Backend Logic Audit

**Scope:** billing settlement, invoice draft issuance, cash close calculations,
adjustment and refund reporting, and transaction audit history.

## Findings fixed

| Area | Defect | Correction |
| --- | --- | --- |
| Draft invoices | A draft could be edited with money already received and then issued without creating a payment ledger row. The invoice showed a paid amount that daily collections could not reconcile. | Finalizing a draft now creates its opening payment in the same database transaction, only when the draft is successfully issued. The payment carries the invoice user ID. |
| Adjustments | A balance adjustment changed both `paid` and `balance`, making an accounting correction look like cash received or returned. A credit could also exceed the outstanding balance. | Adjustments now leave actual paid cash unchanged, modify only the balance, and reject a credit larger than the outstanding balance. |
| Cash close | Daily closing cash subtracted card and other non-cash refunds as if cash had left the till. | Cash close now subtracts only cash refunds. The report still shows all refund methods in its refund total. |
| Daily report reconciliation | Adjustment rows were included in the refund total, while the report validator compares refunds against refund-only ledger rows. Any adjustment could therefore make closing-report generation fail. | Refund totals now include only rows of kind `refund`; adjustments remain reported separately. |
| Currency precision | Payment and refund balance updates used raw float inputs and Python's banker's rounding after validation had already rounded to paisa. Half-paisa inputs could make the stored balance disagree with the accepted amount. | Settlement now computes and stores normalized integer-paisa amounts. |
| Audit history | Payment, refund, and adjustment writes did not append audit-log entries despite the ledger's audit expectations. | These operations now log the amount, method/reason, invoice, and acting user after the ledger transaction succeeds. |

## Verification

- `python3 -m compileall -q app.py arati` — passed.
- `git diff --check` — passed.
- Existing suite: `./.venv/bin/python -m pytest tests -q` — **106 passed**.

## Remaining scope

This is a focused audit of the high-risk billing and cash paths, not a formal
accounting or tax compliance certification. Existing tests cover general
ledger, draft, room, and report behavior; they do not exhaustively exercise
simultaneous writes from multiple application processes. For a Windows client
release, run the accounting workflow end-to-end against a copy of the real
business database before replacing the live database.
