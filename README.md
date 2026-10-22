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
- **Rooms** — pick a room, check-in/check-out dates and nightly rate; nights and line totals are
  computed automatically.
- **Catalog** — dishes, services, room types and room numbers.
- **Invoices** — searchable history with type, detail view, reprint, and void (admin only).
- **Documents** — A4 invoice/bill of supply, 80mm thermal PDF, raw ESC/POS to a device.
- **Reports** — date-range sales, VAT collected, payment mix, revenue by category, daily totals,
  CSV export.
- **Staff** — admin and staff accounts with PBKDF2-hashed passwords.
- **Settings** — hotel identity, PAN/VAT, bill prefix, tax rates, date format, invoice copy label,
  default payment terms, return policy, logo path and printer device.

## Requirements

- Python 3.11+
- Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu)
- `reportlab` (installed by the run script)

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

`arati/seed.py` holds the seeded catalog: 5 room types, 10 rooms, 23 dishes and 6 services.

Schema changes are additive (`arati/db.py:migrate`): new columns are added to existing databases
and old rows receive safe defaults. Existing bills are never rewritten.

Menu prices and room rates come from the hotel's public website (October 2026). Only room numbers
`2001`, `2222` and `2224` are published; the rest are placeholders — fix them in
**Catalog → Rooms** before going live. The PAN/VAT field is intentionally blank until the hotel's
real number is entered in Settings; no number is invented.

## Operations

```bash
# back up the database and PDFs (safe while the till is open)
python3 scripts/backup.py --out ./backups --keep 14

# restore a backup; the current data is kept as *.pre-restore-<timestamp>
python3 scripts/restore.py ./backups/arati-backup-YYYYmmdd-HHMMSS --yes

# build a versioned release archive with checksum
./scripts/build_release.sh
```

Configuration is optional and read from the environment:

| Variable | Default | Purpose |
|---|---|---|
| `ARATI_DB` | `./arati.db` | database path (keep it in a `700` directory) |
| `ARATI_INVOICE_DIR` | `./invoices` | generated PDFs |
| `PYTHON` | `python3` | interpreter used by `run.sh` |

See [RELEASE.md](RELEASE.md) for the verification record, deployment steps and rollback plan.

## Tests

```bash
./.venv/bin/python -m pytest tests -q
```

29 tests cover invoice arithmetic (service charge, VAT, discounts, non-taxable lines, rounding),
Tax Invoice vs Bill of Supply, amount in words, payment status, schema bootstrap and migration,
bill numbering and persistence, voiding, reports, and PDF/ESC-POS generation.

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
arati/db.py             schema, additive migrations, auth, billing, reports
arati/money.py          invoice arithmetic, amount in words
arati/invoice.py        A4 invoice / bill of supply, thermal PDF, ESC/POS
arati/seed.py           Arati Hotel catalog
arati/ui.py             theme and widgets
arati/screens/          billing, invoices, catalog, reports, staff, settings
data/site-scrape/       scraped hotel catalog used to seed the app
tests/                  pytest suite
```

## License

MIT. The original BilledIn project is MIT licensed; see `LICENSE`.
