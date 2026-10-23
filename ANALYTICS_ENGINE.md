# Analytics engine

## Fit with the application

This feature is implemented inside the existing Python 3.11+, Tkinter, and SQLite desktop
application. The database and authenticated data access already belong to the application process;
starting a second FastAPI service would add a network boundary and deployment burden without adding
capability. The engine therefore uses parameterized SQLite queries and the existing analysis
dashboard. It does not add a dependency, migrate data, or expose a database/API endpoint.

The schema is defined and migrated in `arati/db.py`. The engine reads invoices (`bills`), line items
(`bill_items`), payments, refunds/reversals, rooms, stays, reservations, room charges, settings,
staff attribution, and daily reports. Invoice lines and ledger rows link to invoice IDs/numbers;
stays link to rooms by room number. Existing database indexes support common invoice dates, payment
business dates, and room/stay lookups. SQLite foreign-key checks are included in data-quality
analysis. Source records remain unchanged by analytics.

The inspected workspace database contained six invoices (all on one business date), three
payments, one completed stay, 34 room records (25 active), no refunds, reservations, or daily
reports, no expense table, and no foreign-key violations. This is a small snapshot, not enough
history for forecasting or historical room-capacity reconstruction. The production database may
have different counts; the engine queries it at runtime.

## Metric definitions and policies

Money is accumulated in integer paisa through `arati.money` helpers. SQLite is the source of truth;
display conversion happens after aggregation. Voided and draft invoices are excluded.

| Metric | Definition |
|---|---|
| Gross sales | Grand totals of eligible invoices issued within the selected inclusive business-date range. |
| Discounts | Bill-level discount plus item-level discounts. |
| Net sales | Invoice total less refunds/reversals recorded in the selected period, following the existing report definition. |
| Payments/collections | Payment ledger amounts by payment business date, regardless of the invoice date. |
| Receivables | Issued invoice balances reconstructed from payments, refunds, and adjustments through the selected end date. |
| Average invoice | Eligible invoice sales divided by eligible invoice count; empty periods return no value. |
| Category/room revenue | Line amounts less line discounts; invoice-wide discount allocated proportionally across remaining line value, with deterministic paisa rounding. Tax and service charge are excluded. |
| Period comparison | Current inclusive date range versus the immediately preceding range of equal length. Zero previous value is reported as `new_activity` or `no_activity`, without division. |
| Occupancy | Distinct occupied physical room-nights divided by sellable room-night capacity. Overlapping stays are not double-counted and are returned for review. |
| ADR | Net room-line revenue divided by occupied room-nights. |
| RevPAR | Net room-line revenue divided by sellable room-night capacity. |
| Average length of stay | Recorded nights of checked-out stays whose checkout date is in the selected range, divided by those stays. |

Business dates use the hotel's configured timezone, defaulting to `Asia/Kathmandu`. Period ranges
are inclusive. Today's room capacity excludes rooms currently marked under maintenance or awaiting
cleaning. Historical capacity uses the current active room inventory held constant because the
schema has no dated room-status/maintenance snapshots; those occupancy and RevPAR values are
explicitly marked approximate. Historical room-night occupancy comes from stay intervals, not the
current room board. Reservation counts are grouped by reservation creation date because no
cancellation/no-show event timestamp is stored. Room revenue is based on invoice lines; separate
room-charge records are not added again, avoiding double-counting charges already invoiced.

Outstanding balances are reconstructed from ledger activity through the period end rather than
using today's mutable `paid` and `balance` values. The existing schema has no void effective date,
so voided invoices are excluded rather than assigned to an invented historical date. Expenses are
not recorded in this application, therefore expense totals and operating profit are unavailable.

## Quality checks, insights, and forecasts

The quality report returns severity, issue, affected table/record identifiers, count, and a
recommended review action. It checks invoice arithmetic and states, duplicate invoice/payment IDs,
ledger reconciliation, invalid dates/timestamps, missing relationships, nonpositive entries,
high discount ratios (50% or more, for review only), impossible stay states/dates, possible duplicate
room charges, foreign-key violations, and missing past daily reports. It excludes customer contact
and identity fields. Findings are review signals, not automatic corrections or fraud conclusions.

Insights are deterministic and refer to calculated metrics or data-quality findings. The forecast
endpoint in the snapshot intentionally returns no forecast: fewer than 90 distinct sales dates is
reported as insufficient history, and even with more dates a chronological baseline/backtest must
be implemented and reviewed before any prediction is presented. No machine-learning anomaly model
or forecast is claimed.

## Dashboard and deployment

The existing dashboard's Sales details view calls `verified_analytics_snapshot` locally and renders
summary cards, selectable date ranges, trends, category/payment/room charts, period comparisons,
data-quality findings, and deterministic insights. No chart has sample values. The chart helpers use
the existing Tk canvas renderer, so there are no new packages to install and the same local SQLite
database is used on Windows. The snapshot excludes guest details and is JSON-serializable for future
report/export integrations.

Normal app startup refreshes the dashboard from the local database. The current daily-closing
scheduler already generates an idempotent daily sales report in hotel-local time. This work does not
create another report/job or alter closing records; daily report figures now include item-level
discounts and use ledger-derived as-of receivables consistently. Keep the existing database and PDF
backup procedure in the Operations section of `README.md`.

## Verification

Run the repository suite with:

```bash
python -m pytest tests -q
```

Analytics-specific deterministic fixtures are in `tests/test_analytics_engine.py`. They cover
historical receivables, discount allocation, privacy/data-quality output, JSON serialization,
insufficient-history forecast behavior, and period validation. The complete suite also exercises
daily report and scheduler reconciliation. Forecasting, expenses, historical maintenance capacity,
and a separate service API remain unavailable until the data model or deployment needs support them.
