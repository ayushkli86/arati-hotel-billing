# Release records — Arati Hotel billing

Newest first. Each record states what was built, what was actually verified and what is still
open, so a release can be judged on evidence rather than on intent.

| Release | Scope | Decision |
|---|---|---|
| **1.1.0** — [Hotel management suite](#release-110--hotel-management-suite) | rooms, stays, payments, dashboard, reports, sales analysis, midnight closing, printer settings, permissions | **Ready with documented limitations** |
| [1.0.0](#release-100--invoice-design-billing-form-and-release-hardening) | invoice design, billing form, release hardening | Ready with documented limitations |

---

## Release 1.1.0 — Hotel management suite

Commits `7a2a67d` and `7dd8a97`, both pushed to `origin/main`. This is still a **desktop Tkinter +
SQLite** application: no web server, HTTP API or customer-facing endpoint exists, so the hosting,
cookie, CSRF and server-side authorization items of a web checklist remain N/A and are answered
with the local equivalents (file permissions, backup job, in-process permission checks).

### A. Implementation

#### Features added in this pass

- **Room inventory as data** — 25 rooms (`101`–`125`) exist as `rooms` rows pointing at a room
  type, with a floor. The list is editable from the Room Management screen and the
  `room_numbers` setting; the hotel's published numbers (`2001`, `2222`, `2224`) are kept in
  `arati/seed.py` as the alternative.
- **Room state** — occupancy, reservation and housekeeping (`clean`, `needs_cleaning`,
  `maintenance`) are separate fields, so a room can be dirty, reserved, occupied or out of
  service independently. A room under maintenance refuses check-in.
- **Stays** — reservation, check-in, extend, extra charges and check-out. A stay owns one folio
  invoice, so room charges land in the ordinary `bills`/`bill_items` tables and are settled by the
  ordinary `payments` table. There is no second financial ledger.
- **Cash ledger** — `payments` and `refunds` tables. A payment is dated by the moment the money
  changed hands, not by the invoice date, so money received today for last month's invoice counts
  as today's collection and not as today's sale. Refunds and reversals are new rows; nothing is
  edited away. The payment taken at the time of sale is written to the ledger automatically, and
  pre-ledger invoices are backfilled once at start-up.
- **Dashboard** — today's gross sales, net sales, collections, cash in, outstanding, room revenue,
  invoices issued and occupancy, each labelled so sales and collections cannot be confused.
- **Reports** — daily sales, monthly sales, custom range, payment collection, outstanding
  invoices (aged), refunds and adjustments, employee sales, room occupancy, room revenue and the
  operations summary; each filterable, printable and downloadable as PDF.
- **Sales analysis** — sales and collection trends, revenue by category, room, payment method and
  employee, refund and discount trends, headline metrics, and period-over-period comparison.
- **Midnight closing** — the previous business day is closed in the hotel's timezone
  (`Asia/Kathmandu`, `00:05`) by a background thread, and a Daily Sales and Operations Report PDF
  is written. The job is **idempotent** (a second run records `skipped` and changes nothing),
  **recoverable** (missed days are generated on the next start) and **non-destructive** (it reads
  the ledger and writes a report, never edits an invoice). Regenerating a day bumps the version,
  supersedes the old row and leaves an audit line.
- **Printer settings** — paper size, margins, logo visibility, header/footer, contact and tax
  details, copies, default workflow and default device, used by the print preview, the PDF
  download and the thermal receipt.
- **Permissions** — 38 named permissions over two roles, checked in the UI *and* re-checked in
  the data layer, so a hidden button is never the only thing standing between a staff account and
  a refund. An unknown permission is denied, so a typo fails closed.

#### Files changed

| File | Change |
|---|---|
| `arati/rooms.py` | new — inventory, room state, reservations, stays, charges, occupancy |
| `arati/payments.py` | new — payments, refunds, adjustments, legacy backfill |
| `arati/reports.py` | new — the report queries behind the reports screen |
| `arati/analysis.py` | new — trends, breakdowns, headline metrics, period comparison |
| `arati/daily_report.py`, `arati/daily_report_pdf.py` | new — business-day close and its PDF |
| `arati/scheduler.py` | new — midnight job, catch-up, regeneration, run history |
| `arati/business_time.py` | new — business timezone and business-day boundaries |
| `arati/permissions.py` | new — roles, permissions, fail-closed checks |
| `arati/printing.py`, `arati/report_pdf.py`, `arati/invoice_html.py` | new/updated — print layout and PDF rendering |
| `arati/db.py` | new tables, additive migrations, room and payment bootstrap |
| `arati/seed.py` | room numbers moved to `arati/rooms.py`; published numbers kept here |
| `arati/screens/dashboard.py`, `rooms_screen.py`, `payments.py`, `customers.py`, `printer.py`, `analysis.py`, `reports.py`, `login.py` | new/updated screens |
| `app.py` | shell with the new screens, role-aware navigation, document rendering, scheduler |
| `scripts/close_day.py` | new — the closing job as a command line, for cron |
| `tests/test_hotel_core.py` | new — rooms, stays, payments, closing, permissions |
| `tests/smoke_app.py` | new — builds every screen and checks the staff restrictions |
| `README.md`, `RELEASE.md` | documentation |

#### Database changes (additive only)

New tables: `payments`, `refunds`, `reservations`, `stays`, `room_charges`, `daily_reports`,
`scheduler_runs`, `audit_log`.
New columns: `rooms.nightly_rate`, `rooms.housekeeping`, `bill_items.stay_id`.
New settings: `business_timezone`, `auto_close_enabled`, `close_time`, `payment_methods`,
`room_numbers`, `cash_opening_balance`, `backup_dir`, `backup_hour`, `backup_retention_days` and
the `printer_*` keys.

No table is dropped and no existing bill is rewritten. Migrations run at start-up, are idempotent
and only add columns.

### B. Verification

#### Checks actually executed

| Check | Result |
|---|---|
| `pytest tests -q` | **93 passed** in 5.87s |
| `xvfb-run ./.venv/bin/python tests/smoke_app.py` | 12 screens built cleanly (dashboard, billing, invoices, customers, rooms, payments, reports, analysis, catalog, printer, staff, settings) |
| Smoke test, staff account | denied printer settings, staff, hotel settings and analysis |
| `scripts/close_day.py` | closes a day, writes the report PDF, second run reports `skipped` |
| `scripts/close_day.py --catch-up` | generates the missed days, no duplicate sales or payments |
| `scripts/close_day.py --date … --force` | regenerates as v2, the old row is `superseded`, audit line written |
| Backup → restore | restored, `integrity_check: ok` (see 1.0.0 for the drill) |
| Git | `7a2a67d`, `7dd8a97` pushed to `origin/main` |

#### What the financial figures depend on

- Every amount in the reports comes from the same ledger the till writes: `bills` for sales,
  `payments` for money in, `refunds` for money out. Sales and collections are read from different
  tables on purpose.
- The daily report reconciles the day before writing it: opening cash + collections − refunds =
  closing cash, and the bill total must equal the sum of its lines. A day that does not reconcile
  is written as `failed` with the reason, not as a clean report.
- Money is stored in rupees as `REAL` and compared in paisa (`arati/money.py`) so rounding never
  decides a total.

### C. Deployment

Unchanged from 1.0.0: build the archive, copy it to the till, `./run.sh`. The new pieces add two
operational notes.

- **The closing job** runs inside the app. If the till is shut at night, schedule the command
  line version instead:
  `5 0 * * * /opt/arati/.venv/bin/python /opt/arati/scripts/close_day.py --catch-up >> /opt/arati/reports/close_day.log 2>&1`
  Set `ARATI_DISABLE_SCHEDULER=1` to stop the in-app job when the cron job owns the schedule.
- **Back up the database and the `reports/` directory** together. The daily report PDFs are the
  audit trail for closed days and are not regenerated from the database.

| Variable | Default | Purpose |
|---|---|---|
| `ARATI_DB` | `./arati.db` | database path (keep it in a `700` directory) |
| `ARATI_INVOICE_DIR` | `./invoices` | generated PDFs |
| `ARATI_REPORT_DIR` | `./reports` | daily closing reports |
| `ARATI_DISABLE_SCHEDULER` | unset | set to any value to stop the in-app midnight closing |

### D. Remaining issues

1. **Nepali invoice text and Bikram Sambat dates — still not implemented.** Blocked on a
   Devanagari shaping engine in the PDF pipeline. This is the same gap as 1.0.0 and is a
   functional gap against a bilingual hotel.
2. **Room numbering is a placeholder.** `101`–`125` is the default; the hotel's real numbering
   must be confirmed in Room Management before go-live.
3. **Housekeeping is state only.** Rooms can be marked clean, needing cleaning or under
   maintenance, and a room out of service refuses check-in, but housekeeping is not yet scheduled
   or reported on.
4. **The daily report is a PDF, not a signed record.** A regenerated day is versioned and audited,
   but a closed day is not cryptographically sealed.
5. **Single-user desktop only.** No server-side authorization; anyone with file access to
   `arati.db` can read it. Use OS accounts and file permissions. The in-process permission checks
   stop a staff account inside the app, not a person with the file.
6. **Not deployed.** No target host or credentials were supplied, so the deployment item is
   "prepared and documented", not "deployed and verified in the target environment".

### E. Release decision

**READY WITH DOCUMENTED LIMITATIONS** — for the agreed English-only, single-till desktop scope.

- Rooms, stays and the cash ledger work end to end and are covered by tests — verified
- Reports and analysis read the same ledger the till writes — verified
- The closing job is idempotent, recovers missed days and versions regenerations — verified
- Staff accounts are held to the permission list in the data layer, not just in the UI — verified
- Every screen builds and the app starts — verified
- Nepali rendering, real room numbering and deployment to a live host — **not done**

---

## Release 1.0.0 — Invoice design, billing form and release hardening

Scope: the redesigned Nepali-format invoice (Tax Invoice / Bill of Supply), the billing form, and
release hardening. This is a **desktop Tkinter + SQLite** application: there is no web server,
browser frontend, HTTP API or customer-facing endpoint, so checklist items about HTTP hosting,
cookies, XSS, CSRF and server-side authorization do not apply. They are marked N/A with the
reason rather than silently ticked.

### A. Implementation

#### Features completed in this pass

- Invoice types: **Tax Invoice** (service charge + 13% VAT) and **Bill of Supply** (no VAT).
- Print-ready A4 document: customer block, 10-column items table (S.N., description, code, unit,
  qty, rate, taxable, VAT %, VAT, amount), totals, amount in words, signatures, payment terms,
  return policy, copy label, `Page x of y`, repeated table headers.
- Entry form: customer / invoice & stay / items sections plus a live summary; **Preview invoice**
  renders a PDF without saving.
- Validation: 9-digit PAN/VAT when provided, business invoices need a customer name, positive
  quantities, non-negative prices, ISO dates.
- Exact **Decimal** arithmetic with half-up rounding to paisa (replaces float maths).
- Additive schema migration with backfill of the taxable base for bills saved before it was stored.
- Fixed **taxable amount always printing 0.00** on saved bills (missing column, missing insert).
- Fixed **startup crash ("database is locked")** when a second instance opened a database held by
  the running till.
- Double-submit guard so a double click cannot issue two invoices.
- Concurrency-safe invoice numbering (retry on unique collision), WAL journal, 5s busy timeout.
- Database and sidecar files forced to mode `600`; invoices directory `700`.
- Config overrides: `ARATI_DB`, `ARATI_INVOICE_DIR`.
- Backup/restore tooling with SHA-256 manifests and pre-restore safety copies.
- Versioned release archive with checksum, excluding database, invoices and virtualenv.

#### Files changed

| File | Change |
|---|---|
| `arati/money.py` | Decimal arithmetic, Tax Invoice / Bill of Supply, amount in words, payment status |
| `arati/db.py` | new columns + additive migration, taxable_net persistence + backfill, WAL/busy timeout/permissions, retrying `create_bill` |
| `arati/invoice.py` | redesigned A4 layout, 10-column table, page numbering, thermal + ESC/POS updates |
| `arati/screens/billing.py` | redesigned form, live summary, preview, invoice type, validation, submit guard |
| `arati/screens/bills.py` | invoice type column/detail, VAT-aware totals |
| `arati/screens/admin.py` | settings for copy label, terms, return policy, logo, date format |
| `app.py` | invoice dir override, `render_preview`, minimum window size |
| `scripts/backup.py`, `scripts/restore.py`, `scripts/build_release.sh` | new (backup, restore, packaging) |
| `tests/` | 41 tests incl. release checks (concurrency, immutability, env, multi-page) |
| `README.md`, `RELEASE.md` | documentation |

#### Database changes (additive only)

`bills`: `taxable_net`, `bill_type`, `customer_type`, `payment_terms`, `prepared_by`, `received_by`
`bill_items`: `code`

Existing rows receive defaults (`tax`, `individual`, `0`); no bill is rewritten, no table is
dropped. `taxable_net` is backfilled only for tax bills with VAT and a zero base.

#### Dependencies

No new runtime dependencies. `reportlab>=4.0` (verified on 5.0.0 and 5.0.1). `pytest` and
`pip-audit` are development-only.

### B. Verification

#### Tests actually executed

| Check | Result |
|---|---|
| `pytest tests -q` (working tree) | **41 passed** |
| `pytest tests -q` in a fresh venv installed from the release archive | **41 passed** |
| App started from the extracted archive, fresh DB | login, all 6 screens, bill issued, PDF written |
| GUI: full screen walkthrough + save | 0 errors |
| GUI: catalog / staff / settings writes, room bill, void, CSV export | 0 failures |
| GUI: login screen (wrong then right password) | 0 failures |
| GUI: layout overflow scan at 1440×900 and 1280×760 | 0 functional failures |
| 20 concurrent writers, 8 threads | 20 unique invoice numbers, 20 rows |
| Backup → simulated data loss (0 bills) → restore | 3 bills restored, `integrity_check: ok` |
| Tampered backup (appended byte) | restore refused, exit 3, checksum mismatch |
| Migration on the real database | 3 bills before and after, totals identical |
| Existing bill reprinted through the new template | taxable 4,950.00 / VAT 707.85 / total 6,152.85 |
| `pip-audit -r requirements.txt` | **No known vulnerabilities found** |
| `ruff check` | 1 real issue found and fixed (unused import); style-only items remain |
| `pip check` (project deps) | no conflicts among `reportlab`/`pytest` |

#### Financial results

| Scenario | Result |
|---|---|
| 2 nights @ 4,500 + 2 × 490, 10% discount | subtotal 9,980.00 → discount 998.00 → taxable 8,982.00 → VAT 1,284.43 → SC 898.20 → **total 11,164.63** |
| Same bill, 5,000 paid | balance 6,164.63, status **Partially paid** |
| Mixed taxable/exempt (1,000 + 1,000 exempt) | VAT 143.00, total 2,343.00 |
| Bill of Supply, 1,000 | VAT 0.00, total 1,100.00, “Not applicable” printed |
| Amount in words | “Nepalese Rupees Eleven Thousand One Hundred Sixty-Four and Paisa Sixty-Three Only” |
| 60-line invoice | 3 pages, header repeated on every page, no UI chrome |

#### Nepali / English PDF verification

- **English: verified** — rendered and text-extracted for all five scenarios above.
- **Nepali: not implemented and not verified.** No Devanagari shaping engine
  (`uharfbuzz`/`raqm`) is available to the PDF renderer, so Nepali glyphs would print with broken
  conjuncts. The earlier decision was English-only. Nepali text and Bikram Sambat dates remain an
  open requirement, not a completed one.

#### Security checks performed

- Dependency audit: no known vulnerabilities.
- SQL: all user values are bound parameters; the only interpolated SQL is `PRAGMA`/`ALTER` built
  from fixed internal names.
- Passwords: PBKDF2-HMAC-SHA256, 120,000 rounds, per-user salt, constant-time compare.
- Secrets: none in source; no credentials or keys committed.
- File permissions: database and sidecars `600`, invoices `700`.
- Access control: admin-only screens (Staff, Settings, catalog edits, void) enforced in the UI;
  data lives in a local file, so OS file permissions are the real boundary.
- Errors: no stack traces or secrets in the PDF or normal UI paths; save failures surface a
  message box instead of losing the bill.

### C. Deployment

This is an on-premise desktop application; “deployment” means installing the release folder on the
front-desk PC. **No target environment was provided, so nothing was deployed or published.**

#### Exact commands

```bash
# build the release
./scripts/build_release.sh            # -> dist/arati-billing-1.0.0.tar.gz (+ .sha256)

# install on the till
sha256sum -c arati-billing-1.0.0.tar.gz.sha256
tar -xzf arati-billing-1.0.0.tar.gz
cd arati-billing-1.0.0
./run.sh                              # creates .venv, installs reportlab, starts the app
```

Requirements: Python 3.11+ (verified on 3.13.5), Tkinter (`python3-tk` on Debian/Ubuntu).

#### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ARATI_DB` | `<app>/arati.db` | database location; put it in a `700` directory |
| `ARATI_INVOICE_DIR` | `<app>/invoices` | generated PDFs; point at a backed-up volume |
| `PYTHON` | `python3` | interpreter used by `run.sh` |

None are required. No secrets are read from the environment.

#### Migrations

Run automatically at startup (`db.bootstrap` → `db.migrate`). Additive only; safe to run on every
launch and idempotent. Back up before the first launch of a new version anyway.

#### Backup and rollback

```bash
python3 scripts/backup.py --out /path/to/backups     # safe while the till is open
python3 scripts/restore.py /path/to/backup --yes     # keeps a .pre-restore copy
```

Rollback of a release: stop the app, restore the pre-upgrade database backup, and start the
previous release folder. Because migrations only add columns and backfill a derived value, the
previous version still opens a migrated database (it ignores the new columns).

#### Hosting notes (N/A)

There is no cPanel/Node/PHP/HTTP deployment, no static assets or web fonts to serve, no reverse
proxy, no TLS or cookie settings, and no health endpoint. The analogous controls are file
permissions, the backup script and a scheduled backup job (e.g. cron:
`0 22 * * * cd /opt/arati && python3 scripts/backup.py`).

### D. Remaining issues

1. **Nepali invoice text and Bikram Sambat dates — not implemented.** Blocked on Devanagari text
   shaping in the PDF pipeline; this is a functional gap against the bilingual requirement.
2. **Draft / held invoices — not implemented.** A bill is issued when saved; there is no edit-in-
   place workflow, so “save draft / edit draft” is unmet.
3. **Per-line discounts — not implemented.** Discount is per invoice only.
4. **VAT-inclusive pricing — not supported.** Rates are treated as VAT-exclusive.
5. **Legal/tax confirmation required.** The app defaults to 10% service charge and 13% VAT and
   does not claim IRD compliance. The hotel must confirm its PAN/VAT registration, which
   transactions may be a Bill of Supply, and whether service charge is VATable. The PAN/VAT field
   ships blank on purpose — no number is invented.
6. **Single-user desktop only.** No server-side authorization; anyone with file access to
   `arati.db` can read it. Use OS accounts and file permissions.
7. **Remaining lint items are stylistic** (broad `except` used deliberately around save/render
   guards; `dict()` in tests). No functional findings.
8. **No real-device printer test.** ESC/POS output is generated and tested as bytes, but no
   physical thermal printer was available to confirm paper width and cut behaviour.
9. **Not deployed.** No target host or credentials were supplied, so the deployment checklist item
   is “prepared and documented”, not “deployed and verified in the target environment”.

### E. Release decision

**READY WITH DOCUMENTED LIMITATIONS** — for the agreed English-only, single-till desktop scope.

All eight checklist items are addressed one way or another:

- Invoice saves and reopens correctly — verified
- Calculations and VAT verified — verified
- Existing data and permissions preserved — verified
- Nepali and English PDFs tested — English verified, **Nepali not implemented**
- A4 printing and multi-page invoices checked — verified
- Production build passes — verified (archive, fresh install, 41 tests, app start)
- Environment variables and deployment configured — supported and documented, **not deployed**
- Backup and rollback plan prepared — implemented and drilled

Not shippable as “bilingual and fully compliant”: Nepali rendering and the tax/legal confirmation
remain open, and no deployment to a real environment has been performed.
