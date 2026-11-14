# Arati Hotel Billing System — Resume Entry

Copy-paste this into your resume (adjust dates/technologies as needed):

---

## **Arati Hotel Billing System** | *Full-Stack Developer* | `Oct 2024 – Present`

**Cross-platform desktop POS & billing software for a 25-room hotel in Sankhuwasabha, Nepal** — handles room stays, restaurant orders, events, and Nepali-compliant tax invoices on a single platform.

**Tech Stack:** Python 3.11, Tkinter (desktop), FastAPI + SQLAlchemy (web), SQLite, ReportLab/WeasyPrint (PDF), ESC/POS thermal printing, pytest (93 tests), GitHub Actions CI/CD

### Key Achievements
- **Built end-to-end billing workflow**: customer check-in → item grid (rooms/dishes/services) → live totals → VAT/Service-charge calculation → A4 tax invoice / bill of supply / 80mm thermal receipt / ESC-POS raw print
- **Implemented Nepali tax compliance**: VAT (13%), service charge (10%), Bill of Supply vs Tax Invoice per bill, amount-in-words, PAN/VAT snapshotting — all calculations in pure Python (`arati/money.py`) with 93 unit tests covering edge cases
- **Room management system**: 25 rooms with reservations, check-in/out, deposits, extra charges, housekeeping/maintenance states separate from occupancy, stay history, room-specific invoices
- **Midnight business-day closing**: automatic daily reconciliation in Asia/Kathmandu timezone, idempotent catch-up for missed days, generates Daily Sales & Operations Report PDF
- **Analytics & reporting dashboard**: daily/monthly/date-range sales, payment-method breakdown, outstanding, refunds, cashier, occupancy, revenue reports — all downloadable/printable
- **FastAPI web front-office**: browser-based 3-column Create Invoice screen, Room Board, separate SQLAlchemy DB, JWT auth
- **Windows standalone build**: PowerShell script produces portable `AratiHotel.exe` (no Python required on client) via PyInstaller + WeasyPrint GTK runtime
- **Additive schema migrations**: `arati/db.py:migrate` adds columns with safe defaults, never rewrites historical bills
- **Role-based permissions**: admin/staff with PBKDF2-hashed passwords, screen-level + data-layer permission checks

### Architecture Highlights
- **Single source of truth**: on-screen form, stored bill, PDF, and thermal print all use identical calculation engine
- **Audit-first design**: payments/refunds/reversals are append-only; voids require admin; daily close is immutable once run
- **Offline-first desktop app**: zero network dependency for core billing; web app optional for front-desk mobility

### Links
- **GitHub:** `https://github.com/<your-username>/arati-hotel-billing` (replace with your actual repo URL)
- **Live demo:** (add if you deploy the web app)

---

## Short Bullet Version (for compact resume)

- **Arati Hotel Billing System** — Cross-platform desktop POS (Tkinter) + FastAPI web app for 25-room hotel in Nepal; Nepali VAT/Service-charge compliance, thermal/ESC-POS printing, midnight auto-close with PDF reports, 93-test suite, Windows standalone exe build
- **Stack:** Python 3.11, Tkinter, FastAPI, SQLAlchemy, SQLite, ReportLab, WeasyPrint, pytest, GitHub Actions
- **Scope:** Full lifecycle — requirements → schema → UI → tax logic → printing → deployment → CI/CD

---

## Talking Points for Interviews

| Question | Your Answer |
|----------|-------------|
| "Walk me through the tax calculation" | Subtotal → discount → service charge (10% of net) → VAT (13% of taxable net + taxable share of service charge). Bill of Supply zeroes VAT. All rates snapshotted per bill. |
| "How do you handle schema changes?" | Additive migrations only — new columns get safe defaults, old rows untouched. Historical bills never rewritten. |
| "What's the hardest bug you fixed?" | Midnight closing across DST/timezone boundaries — solved by anchoring all dates to business-day in Asia/Kathmandu, idempotent catch-up job. |
| "How do you test printing without hardware?" | ESC/POS raw bytes captured in tests; PDF output diffed against golden files; thermal receipt layout unit-tested via ReportLab canvas inspection. |
| "Why Tkinter over Electron/Flutter?" | Zero runtime dependency on client Windows machines; 15 MB standalone exe; native print dialog + ESC/POS direct to USB/serial; team knows Python. |

---

## Optional: Add to GitHub Profile README

Create/update `~/.github/README.md` (or your profile repo) with:

```markdown
## 🏨 Arati Hotel Billing System
Cross-platform desktop POS + FastAPI web app for a 25-room hotel in Nepal.
- **Nepali tax compliant**: VAT 13%, service charge 10%, Bill of Supply / Tax Invoice per bill
- **Prints**: A4 invoice, 80mm/58mm thermal, ESC/POS raw
- **Auto daily close**: midnight Asia/Kathmandu, idempotent catch-up, PDF operations report
- **93 tests** covering arithmetic, migrations, payments, room workflow, daily close
- **Windows standalone exe** (no Python on client)

[View on GitHub](https://github.com/<your-username>/arati-hotel-billing)
```

---

**Next steps:**
1. Replace `<your-username>` with your actual GitHub username
2. Add the GitHub repo URL to your resume
3. If you deploy the web app (Vercel/Render/Railway), add the live demo link
4. Pin the repo on your GitHub profile (Settings → Pinned repositories)