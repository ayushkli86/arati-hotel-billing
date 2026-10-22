# Arati Hotel — Billing

Desktop billing software for **Arati Hotel, Khandbari-01, Sankhuwasabha**. Front-desk staff put
room stays, restaurant orders and event services on one invoice and print a Nepali-style
**Tax Invoice** or **Bill of Supply**, plus an optional 80mm thermal receipt.

Built on the structure of [BilledIn](https://github.com/mahadev0811/BilledIn) (Tkinter + SQLite
desktop POS), rewritten cross-platform and adapted for hotel billing. Menu items and room rates
are seeded from the hotel's public website.

## Invoice design

The printed invoice follows common Nepali business practice:

- **Header** — logo (optional), registered name, address, phone, email, website, PAN/VAT number
  (only if configured), document title, copy label, invoice number, date and time.
- **Document type** — `TAX INVOICE` (VAT charged) or `BILL OF SUPPLY` (no VAT). The type is chosen
  per bill and snapshotted, so old bills keep their treatment.
- **Customer block** — name, address, phone, PAN/VAT number, individual/business, and stay details
  (room, dates, nights) when the bill includes a room.
- **Items table** — S.N., description, code, unit, qty, rate, taxable amount, VAT %, VAT amount,
  amount. Headers repeat when the bill runs to another page.
- **Totals** — subtotal, discount, taxable amount, VAT (or “Not applicable”), service charge,
  grand total, amount paid, balance due, payment method and payment status.
- **Amount in words** — English, generated from the grand total including paisa.
- **Footer** — received by / prepared by / authorised signatory lines, payment terms, return
  policy, notes, thank-you line and `Page x of y`.

Print output is white with black text, thin rules and A4 portrait margins; no UI chrome appears on
paper. The on-screen form, the stored bill and the PDF all use the same calculation
(`arati/money.py`) and the same stored totals.

## Features

- **Billing form** — customer section, invoice/stay section, item grid and a live summary column
  with totals, amount in words and payment status. Preview renders a PDF without saving.
- **Dashboard** — today's gross sales, net sales, collections, cash in, outstanding, room revenue,
  invoices issued and room occupancy, each labelled so sales and collections are never confused.
- **Room management** — 25 rooms (101–125 by default) as database records with reservations,
  check-in/check-out, deposits, extra charges, housekeeping and maintenance states kept separate
  from occupancy, room rates, stay history and a room invoice.
- **Catalog** — dishes, services, room types and room numbers.
- **Invoices** — searchable history with type, detail view, reprint, and void (admin only).
- **Payments** — receive money against an invoice, with cash, card, eSewa, Khalti, Fonepay, bank
  transfer and room credit; refunds and reversals are recorded, never edited into history.
- **Documents** — A4 invoice/bill of supply, 80mm and 58mm thermal PDF, raw ESC/POS to a device.
- **Printer settings** — paper size, margins, logo visibility, header/footer, contact details and
  tax details, used by the print preview and the PDF download of the same document.
- **Reports dashboard** — daily, monthly, date-range, payment, outstanding, refund, cashier,
  occupancy and revenue reports, each downloadable and printable.
- **Sales analysis** — trends, revenue by category/room/payment method/cashier, average invoice
  value, occupancy rate and period comparisons, computed from the ledger.
- **Midnight closing** — the previous business day is closed automatically in the hotel's
  timezone (Asia/Kathmandu), a Daily Sales and Operations Report PDF is written, and missed days
  are recovered on the next start. The job is idempotent: running it twice changes nothing.
- **Staff** — admin and staff accounts with PBKDF2-hashed passwords, each screen behind a named
  permission that is checked again in the data layer.
- **Settings** — hotel identity, PAN/VAT, bill prefix, tax rates, date format, invoice copy label,
  default payment terms, return policy, logo path and printer device.

## Requirements

- Python 3.11+
- Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu)
- `reportlab`, `weasyprint` and `nepali-datetime` (installed by the run script)

## Run

```bash
cd arati-hotel-billing
./run.sh
```

First sign-in: **admin / arat123** — change it on the Staff screen before real use.

Bills live in `arati.db`; PDFs go to `invoices/` (receipts in `invoices/thermal/`).

## Tax model

```
subtotal       = Σ(qty × rate)
less discount  (one overall discount per bill, % or amount)
service charge = net × service_charge_rate        (default 10%)
VAT            = (taxable net + taxable share of service charge) × vat_rate   (default 13%)
grand total    = net + service charge + VAT
balance        = grand total − amount paid
```

- **Bill of Supply** sets VAT to zero and prints “Not applicable”; the service charge still applies.
- Items flagged non-taxable are excluded from the VAT base.
- Rates are snapshotted on every bill, so changing them later never rewrites history.

## Data and upgrades

`arati/seed.py` holds the seeded catalog: 5 room types, 23 dishes and 6 services. The room
inventory itself lives in `arati/rooms.py` and is created in the database as rooms `101`–`125`,
which the hotel can renumber from the Room Management screen.

Schema changes are additive (`arati/db.py:migrate`): new columns are added to existing databases
and old rows receive safe defaults. Existing bills are never rewritten.

Menu prices and room rates come from the hotel's public website (October 2026). Only room numbers
`2001`, `2222` and `2224` are published; the default `101`–`125` numbering is a placeholder —
confirm the hotel's real numbering in **Room Management** before going live. The PAN/VAT field is
intentionally blank until the hotel's real number is entered in Settings; no number is invented.

## Operations

```bash
# back up the database and PDFs (safe while the till is open)
python3 scripts/backup.py --out ./backups --keep 14

# restore a backup; the current data is kept as *.pre-restore-<timestamp>
python3 scripts/restore.py ./backups/arati-backup-YYYYmmdd-HHMMSS --yes

# close a business day by hand (the app also does this at midnight)
python3 scripts/close_day.py                    # yesterday
python3 scripts/close_day.py --catch-up         # every missed day
python3 scripts/close_day.py --date 2026-03-14 --force   # regenerate, keeping the old version

# build a versioned release archive with checksum
./scripts/build_release.sh
```

The closing job can also run from cron on a till that is shut at night:

```cron
5 0 * * * /path/to/.venv/bin/python /path/to/scripts/close_day.py --catch-up >> /path/to/reports/close_day.log 2>&1
```

Configuration is optional and read from the environment:

| Variable | Default | Purpose |
|---|---|---|
| `ARATI_DB` | `./arati.db` | database path (keep it in a `700` directory) |
| `ARATI_INVOICE_DIR` | `./invoices` | generated PDFs |
| `ARATI_REPORT_DIR` | `./reports` | daily closing reports |
| `ARATI_DISABLE_SCHEDULER` | unset | set to any value to stop the in-app midnight closing |
| `PYTHON` | `python3` | interpreter used by `run.sh` |

See [RELEASE.md](RELEASE.md) for the verification record, deployment steps and rollback plan.

## Tests

```bash
./.venv/bin/python -m pytest tests -q
```

93 tests cover invoice arithmetic (service charge, VAT, discounts, non-taxable lines, rounding),
Tax Invoice vs Bill of Supply, amount in words, payment status, schema bootstrap and migration,
bill numbering and persistence, voiding, payments and refunds, the 25-room workflow and its
safeguards, the daily closing job (timezone boundaries, idempotency, missed-day recovery,
regeneration) and PDF/ESC-POS generation.

A screen smoke test boots the real application and builds every screen, then checks that a staff
account cannot open the admin-only ones:

```bash
xvfb-run -a ./.venv/bin/python tests/smoke_app.py
```

## Known limits

- Invoice text is **English only**. This machine has no Devanagari text-shaping engine
  (`uharfbuzz`/`raqm`), so Nepali glyphs would print with broken conjuncts; Bikram Sambat dates
  are not shown for the same reason (no BS library). Both can be added once a shaping engine is
  available.
- Discounts are per invoice, not per line.
- There is no draft/held-bill state; a bill is issued when saved.

## Layout

```
app.py                  entry point, login, sidebar, document rendering
arati/db.py             schema, additive migrations, auth, billing, payments, reports
arati/money.py          invoice arithmetic, amount in words
arati/invoice.py        A4 invoice / bill of supply, thermal PDF, ESC/POS
arati/invoice_html.py   print document (browser print CSS) used by the print/download path
arati/printing.py       paper size, margins and layout options for printing
arati/report_pdf.py     PDF renderer for the report screens
arati/rooms.py          rooms, reservations, stays, charges, housekeeping
arati/payments.py       payments, refunds and reversals
arati/customers.py      customer records
arati/reports.py        report queries and figures
arati/analysis.py       sales analysis metrics
arati/daily_report.py   business-day closing and reconciliation
arati/daily_report_pdf.py  the Daily Sales and Operations Report PDF
arati/scheduler.py      midnight closing job, catch-up and regeneration
arati/business_time.py  business timezone and business-day boundaries
arati/permissions.py    roles and permissions
arati/preview.py        print preview window
arati/seed.py           Arati Hotel catalog
arati/ui.py             theme and widgets
arati/fonts/            bundled fonts for the PDF documents
arati/screens/          dashboard, billing, invoices, customers, rooms, payments, reports,
                        analysis, catalog, printer settings, staff, hotel settings
data/site-scrape/       scraped hotel catalog used to seed the app
scripts/                close_day, backup, restore, release build
tests/                  pytest suite and the screen smoke test
```

## License

MIT. The original BilledIn project is MIT licensed; see `LICENSE`.
