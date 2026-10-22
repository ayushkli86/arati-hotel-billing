# Release record — Arati Hotel billing 1.0.0

Scope: the redesigned Nepali-format invoice (Tax Invoice / Bill of Supply), the billing form, and
release hardening. This is a **desktop Tkinter + SQLite** application: there is no web server,
browser frontend, HTTP API or customer-facing endpoint, so checklist items about HTTP hosting,
cookies, XSS, CSRF and server-side authorization do not apply. They are marked N/A with the
reason rather than silently ticked.

## A. Implementation

### Features completed in this pass

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

### Files changed

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

### Database changes (additive only)

`bills`: `taxable_net`, `bill_type`, `customer_type`, `payment_terms`, `prepared_by`, `received_by`
`bill_items`: `code`

Existing rows receive defaults (`tax`, `individual`, `0`); no bill is rewritten, no table is
dropped. `taxable_net` is backfilled only for tax bills with VAT and a zero base.

### Dependencies

No new runtime dependencies. `reportlab>=4.0` (verified on 5.0.0 and 5.0.1). `pytest` and
`pip-audit` are development-only.

## B. Verification

### Tests actually executed

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

### Financial results

| Scenario | Result |
|---|---|
| 2 nights @ 4,500 + 2 × 490, 10% discount | subtotal 9,980.00 → discount 998.00 → taxable 8,982.00 → VAT 1,284.43 → SC 898.20 → **total 11,164.63** |
| Same bill, 5,000 paid | balance 6,164.63, status **Partially paid** |
| Mixed taxable/exempt (1,000 + 1,000 exempt) | VAT 143.00, total 2,343.00 |
| Bill of Supply, 1,000 | VAT 0.00, total 1,100.00, “Not applicable” printed |
| Amount in words | “Nepalese Rupees Eleven Thousand One Hundred Sixty-Four and Paisa Sixty-Three Only” |
| 60-line invoice | 3 pages, header repeated on every page, no UI chrome |

### Nepali / English PDF verification

- **English: verified** — rendered and text-extracted for all five scenarios above.
- **Nepali: not implemented and not verified.** No Devanagari shaping engine
  (`uharfbuzz`/`raqm`) is available to the PDF renderer, so Nepali glyphs would print with broken
  conjuncts. The earlier decision was English-only. Nepali text and Bikram Sambat dates remain an
  open requirement, not a completed one.

### Security checks performed

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

## C. Deployment

This is an on-premise desktop application; “deployment” means installing the release folder on the
front-desk PC. **No target environment was provided, so nothing was deployed or published.**

### Exact commands

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

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ARATI_DB` | `<app>/arati.db` | database location; put it in a `700` directory |
| `ARATI_INVOICE_DIR` | `<app>/invoices` | generated PDFs; point at a backed-up volume |
| `PYTHON` | `python3` | interpreter used by `run.sh` |

None are required. No secrets are read from the environment.

### Migrations

Run automatically at startup (`db.bootstrap` → `db.migrate`). Additive only; safe to run on every
launch and idempotent. Back up before the first launch of a new version anyway.

### Backup and rollback

```bash
python3 scripts/backup.py --out /path/to/backups     # safe while the till is open
python3 scripts/restore.py /path/to/backup --yes     # keeps a .pre-restore copy
```

Rollback of a release: stop the app, restore the pre-upgrade database backup, and start the
previous release folder. Because migrations only add columns and backfill a derived value, the
previous version still opens a migrated database (it ignores the new columns).

### Hosting notes (N/A)

There is no cPanel/Node/PHP/HTTP deployment, no static assets or web fonts to serve, no reverse
proxy, no TLS or cookie settings, and no health endpoint. The analogous controls are file
permissions, the backup script and a scheduled backup job (e.g. cron:
`0 22 * * * cd /opt/arati && python3 scripts/backup.py`).

## D. Remaining issues

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

## E. Release decision

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
