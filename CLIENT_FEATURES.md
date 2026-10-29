# Arati Hotel Billing & Management System
## Complete Feature List for Client Presentation

---

## Executive Summary

**Arati Hotel Billing** is a comprehensive hotel property management and billing system designed specifically for **Arati Hotel, Khandbari-01, Sankhuwasabha**. The system combines a modern web-based front office with robust back-office accounting, room management, and analytics — all running locally with zero cloud dependency.

**Technology Stack:** FastAPI (Python 3.11+), SQLAlchemy + SQLite, Jinja2 + HTMX + Alpine.js, Tailwind CSS
**Deployment:** Local-first (runs on hotel's own hardware), Chrome App Mode for desktop-like experience
**Timezone:** Asia/Kathmandu (Bikram Sambat date support)

---

## 1. Front Desk Operations

### 1.1 Dashboard & Real-Time Overview
- **Live Business Dashboard** — Kathmandu business date, gross/net sales, collections, cash-in, outstanding balances, room revenue, invoice count, occupancy rate
- **Room Board (Visual Grid/List)** — 25+ rooms with color-coded status: Available, Occuped, Dirty/Needs Cleaning, Reserved, Maintenance
- **Real-Time Room Status** — Live filters (Attention, Occupied, Available, Dirty, Reserved, Maintenance, All)
- **Stay Duration Tracking** — Hours/minutes since check-in for occupied rooms
- **Outstanding Balances** — Per-room outstanding amounts with quick collection actions
- **Quick Actions** — Check-in, Check-out, Extend Stay, Room Charge, View Folio, Housekeeping
- **Check-outs Today** — Highlighted rooms with expected departures

### 1.2 Room Management
- **Room Inventory** — Configurable room numbers, types, bed types, floor, nightly rates
- **Room Types & Rates** — Linked to catalog items; type-rate changes propagate unless overridden per room
- **Housekeeping States** — Clean, Dirty, Needs Cleaning, Maintenance, Under Maintenance (separate from occupancy)
- **Room Status Workflow** — Available → Reserved → Occupied → Dirty → Available
- **Reservations** — Future bookings with guest details, check-in/out dates, nightly rate, deposit, source, notes
- **Reservation Ledger** — Filter by status, room, dates; audit trail for cancellations with reasons
- **Walk-in Check-in** — Instant check-in without reservation, captures guest details at arrival
- **Stay Extension** — Extend checkout date with rate recalculation
- **Room Charges** — Add minibar, laundry, phone, service charges to running folio
- **Deposit Handling** — Record deposits at reservation; visible separately for refund reconciliation

### 1.3 Guest Management
- **Guest Directory** — Searchable list with profile editing (name, phone, email, address, PAN/VAT, ID type/number)
- **Customer Types** — Individual / Business classification for invoicing
- **Guest History** — Complete stay history, invoice history, payment history per guest
- **Guest Deactivation** — Admin-only soft delete (retains transaction history)
- **PAN/VAT Capture** — Mandatory for business invoices, printed on Tax Invoices

---

## 2. Billing & Invoicing

### 2.1 Three-Column Invoice Workspace
- **Left Panel** — Customer search/select, stay/room context, invoice type (Tax Invoice / Bill of Supply), language, copy label
- **Center Panel** — Item grid (description, code, unit, qty, rate, discount, taxable, category) with live search from catalog
- **Right Panel** — Live summary: Subtotal, Discount, Service Charge (10% default), VAT (13% default), Grand Total, Amount in Words, Payment Status, Paid/Balance

### 2.2 Invoice Features
- **Draft → Issue Workflow** — Running folios saved as drafts; finalized on issue with sequential numbering (e.g., `ARATI000001`)
- **Multi-Stay Folio** — Single invoice covers room nights + restaurant + services + extras
- **Item Categories** — Food, Beverage, Room, Service (different tax treatment per category)
- **Non-Taxable Items** — Flag items exempt from VAT (e.g., certain services)
- **Line-Level Discounts** — Per-item discount amounts
- **Invoice-Level Discount** — Overall percentage or flat amount
- **Bill Types** — **Tax Invoice** (VAT charged) or **Bill of Supply** (no VAT, prints "Not Applicable")
- **Language Support** — English / Nepali labels (Bikram Sambat dates)
- **Copy Labels** — Customer Copy, Office Copy, Duplicate, Triplicate
- **Payment Terms** — Configurable default (e.g., "Due on Check-out")
- **Notes & Footer Policy** — Return policy, terms, thank-you message printed on invoice

### 2.3 Tax Calculation (Nepal Compliant)
```
Subtotal = Σ(qty × rate)
Less Discount (bill-level + item-level)
Service Charge = Net × 10% (configurable)
VAT = (Taxable Net + Taxable Share of Service Charge) × 13% (configurable)
Grand Total = Net + Service Charge + VAT
Balance = Grand Total − Amount Paid
```
- Rates snapshotted at invoice creation (historical invoices never recalculate)
- VAT-exclusive and VAT-inclusive pricing modes
- Amount in words (English) generated automatically

### 2.4 Document Output
- **A4 Tax Invoice / Bill of Supply** — Professional layout with logo, header, item table, totals, amount in words, signatory lines, page numbers
- **80mm Thermal Receipt** — Compact receipt for POS printers
- **58mm Thermal Receipt** — Alternative roll width
- **PDF Download** — All formats downloadable
- **Print Preview** — Browser print dialog with print CSS (no UI chrome on paper)
- **ESC/POS Raw Output** — Direct thermal printer support
- **Reprint** — Any issued invoice reprintable with original numbers preserved

---

## 3. Payments & Collections

### 3.1 Payment Methods (Configurable)
- Cash
- Card (Visa/Mastercard/ConnectIPS)
- eSewa
- Khalti
- Fonepay
- Bank Transfer
- Room Credit (applied from stay deposit/advance)

### 3.2 Payment Features
- **Partial Payments** — Multiple payments per invoice tracked individually
- **Payment Ledger** — Immutable record: every payment, refund, adjustment is a new row (never edited)
- **Collection Modal** — Quick payment entry from dashboard/room board/invoice
- **Refunds** — Full or partial with reason codes (Service not delivered, Overcharged, Cancelled, Goodwill, Other)
- **Adjustments** — Correction entries with audit trail (Correct earlier entry, Goodwill credit, Service charge waiver, Other)
- **Payment Status** — Issued / Partial / Paid / Void — auto-calculated from ledger
- **Receipt Printing** — 80mm/58mm thermal receipt for each payment

### 3.3 Outstanding & Receivables
- **Outstanding Report** — All unpaid/partially paid invoices with aging
- **Room-Wise Balances** — Live on room board
- **Guest-Wise Statements** — Complete transaction history per guest
- **Ledger-Reconstructed Balances** — Balances computed from payment/refund/adjustment ledger (not mutable fields)

---

## 4. WhatsApp Order Assistant (Digital Channel)

### 4.1 Guest-Facing Ordering
- **Menu Browsing** — Food & drinks from catalog (categories: restaurant, food, beverage)
- **Fulfilment Options** — Pickup, Delivery, Dine-in, Room Delivery
- **Room Booking Requests** — Check-in date, nights, guests, room type → creates booking request for front desk
- **Event/Service Booking** — Spa, conference, laundry, transport from catalog (service category)
- **Conversation State** — Numbered menu flow, context-aware, pauses for human handoff

### 4.2 Staff-Facing Order Management
- **Order Queue** — `/orders` page with filters: Type (Food/Room/Service), Status, Search
- **Order Status Workflow** — New → Confirmed → Preparing → Ready → Completed / Cancelled
- **Guest Notifications** — Automatic WhatsApp updates on status changes
- **Human Handoff** — "Talk to front desk" pauses bot; staff reply from order page
- **Order Details** — Items, fulfilment, room/delivery details, guest contact, staff notes
- **WhatsApp Cloud API Integration** — Meta Business API (production) or local simulator (training)

---

## 5. Reporting & Analytics

### 5.1 Operational Reports
| Report | Description | Export |
|--------|-------------|--------|
| **Daily Sales** | Gross, net, discounts, collections, payment method breakdown, room revenue | CSV, PDF, Print |
| **Monthly Sales** | Aggregated daily totals for calendar month | CSV, PDF, Print |
| **Custom Date Range** | Any from/to business dates | CSV, PDF, Print |
| **Collections** | Payment ledger by date, method, cashier | CSV, PDF, Print |
| **Outstanding / Receivables** | Unpaid invoices with aging, guest, room | CSV, PDF, Print |
| **Refunds & Reversals** | All refund/adjustment entries with reasons | CSV, PDF, Print |
| **Cashier Sales** | Sales attributed to staff user | CSV, PDF, Print |
| **Occupancy** | Room nights sold vs capacity, ADR, RevPAR | CSV, PDF, Print |
| **Room Revenue** | Room-line revenue by room/type | CSV, PDF, Print |
| **Daily Operations Report** | Auto-generated at midnight (PDF) — sales, payments, occupancy, room status, staff attendance | PDF |

### 5.2 Sales Analysis Dashboard (Admin)
- **Trend Charts** — Daily/Weekly/Monthly gross sales, collections, discount ratio
- **Period Comparison** — Current vs. prior period (equal length) with % change
- **Category Breakdown** — Revenue by food/beverage/room/service
- **Room Breakdown** — Revenue, occupancy, ADR, RevPAR per room
- **Payment Method Mix** — Collections by Cash/Card/eSewa/Khalti/Fonepay/Bank/Room Credit
- **Cashier Performance** — Sales per staff member
- **Room KPIs** — Occupancy %, ADR, RevPAR, Average Length of Stay
- **Data Quality Review** — Automated checks:
  - Invoice arithmetic validation
  - Payment ledger reconciliation
  - Missing line items
  - High discount ratios (≥50% flagged for review)
  - Overlapping room stays
  - Orphan payments/refunds
  - Non-positive amounts
  - Foreign key violations
- **Forecast Readiness** — Explicit indicator: requires 90+ business days of history before forecasting enabled

---

## 6. Daily Closing & Reconciliation

### 6.1 Automated Midnight Closing
- **Timezone-Aware** — Runs at configured close time (default 00:05 Asia/Kathmandu)
- **Idempotent** — Running twice produces identical results; safe for retries
- **Missed-Day Catch-up** — On startup, generates reports for any missed business days
- **Versioned Reports** — Each close creates a new version; regeneration preserves history
- **Daily Report PDF** — Professional Daily Sales & Operations Report with:
  - Sales summary (gross, net, discounts, VAT, service charge)
  - Payment method totals
  - Room occupancy & revenue
  - Outstanding receivables (ledger-derived)
  - Refunds & adjustments
  - Staff attendance summary
  - Cashier-wise sales

### 6.2 Manual Controls
- **Admin Regeneration** — Re-run any past business day (keeps old version)
- **Force Regenerate** — Overwrite current version with updated data
- **Report History** — List all generated reports with version, status, timestamps
- **Scheduler Run Log** — Audit trail of every scheduled run (success/failure/message)

---

## 7. Staff & Access Control

### 7.1 Role-Based Access
| Role | Permissions |
|------|-------------|
| **Admin** | Full access: Staff accounts, Hotel settings, Printer settings, Sales Analysis, Void invoices, Daily close regen, Audit logs |
| **Staff (Front Desk)** | Dashboard, Orders, Billing, Invoices, Payments, Menu, Rooms, Reservations, Customers, KOTs, Password change |

### 7.2 Security Features
- **PBKDF2 Password Hashing** — 100,000+ iterations
- **Signed HTTP-Only Session Cookies** — Secure, SameSite=Lax, HttpOnly
- **CSRF Tokens** — All state-changing forms protected
- **Login Throttling** — Per (IP, username) sliding window (default 5 attempts / 15 min)
- **Session Versioning** — Password change invalidates all other sessions
- **Forced Password Change** — New accounts / admin reset require 12+ char password
- **Audit Logging** — Every login, invoice action, payment, refund, settings change, user management

### 7.3 Staff Attendance
- **Daily Check-In/Out** — IP and User-Agent recorded
- **Attendance Report** — Per staff, per day with hours
- **Unique Constraint** — One record per staff per business day

---

## 8. Configuration & Settings

### 8.1 Hotel Identity (Admin)
- Hotel name, address, phone, email, website
- PAN/VAT number (printed on Tax Invoices)
- Logo upload (printed on invoices/receipts)

### 8.2 Invoice Configuration
- Invoice prefix (e.g., "ARATI")
- VAT rate (default 13%)
- Service charge rate (default 10%)
- Default language (English/Nepali)
- Default copy label
- Default payment terms
- Return/refund policy text
- Footer notes

### 8.3 Payment Methods
- Comma-separated list (customizable)
- Order defines UI display order

### 8.4 Date & Display
- Date format (AD / BS / Both)
- Business date timezone (fixed: Asia/Kathmandu)

### 8.5 Printer Settings (Admin)
- **Paper Sizes** — A4, 80mm, 58mm
- **Margins** — Top, bottom, left, right (mm)
- **Header Sections** — Hotel identity, contact, tax details (toggle each)
- **Footer Sections** — Payment terms, return policy, signatory lines, thank-you (toggle each)
- **Logo on Print** — On/Off
- **Copy Count** — 1–3 copies
- **Preview vs Direct Print** — Workflow choice
- **Test Invoice** — Non-persisted preview for layout verification

---

## 9. Catalog & Menu Management

### 9.1 Catalog Items
- **Categories** — Room, Restaurant, Food, Beverage, Service
- **Menu Groups** — Starters, Main Course, Beverages, Room Types, Spa, Laundry, etc.
- **Item Properties** — Name, code, rate, unit (pcs, plate, glass, night, hour), taxable flag, sort order
- **Active/Inactive** — Soft disable without deleting history
- **Room Type Linking** — Room catalog items drive room inventory rates

### 9.2 Seeded Data (Arati Hotel Specific)
- **5 Room Types** — Standard, Deluxe, Suite, Family, Executive (from hotel website)
- **23 Restaurant Dishes** — Nepali, Indian, Chinese, Continental
- **6 Services** — Laundry, Spa, Transport, Conference, WiFi, Parking

---

## 10. Technical & Operational

### 10.1 Data Integrity
- **Additive Migrations** — Schema upgrades never drop columns/data
- **Historical Preservation** — Invoice totals, tax snapshots, rates frozen at creation
- **Soft Deletes** — Guests, users, rooms deactivated (not deleted)
- **Foreign Key Enforcement** — SQLite FK checks enabled
- **WAL Mode** — SQLite Write-Ahead Logging for concurrent read safety

### 10.2 Backup & Recovery
- **Backup Script** — `scripts/backup.py` — database + PDFs, configurable retention
- **Restore Script** — `scripts/restore.py` — preserves current data as `.pre-restore-*`
- **Daily Report Archive** — All closing reports retained indefinitely

### 10.3 Deployment Options
| Mode | Description |
|------|-------------|
| **Desktop Launcher** | `arati_desktop.py` — Starts local server, opens Chrome App Mode window (no URL bar) |
| **Web Server** | `run_web.sh` / `run_web.bat` — Starts FastAPI on `http://127.0.0.1:8000` |
| **Windows EXE** | `scripts/build_windows_exe.ps1` — Standalone executable (no Python needed on client) |
| **Production** | Reverse proxy (nginx) + HTTPS + systemd/service manager |

### 10.4 Environment Configuration
- `ARATI_WEB_DATABASE_URL` — SQLite (default) or PostgreSQL
- `ARATI_WEB_SECRET` — Session signing key (mandatory in production)
- `ARATI_WEB_HTTPS=1` — Secure cookies behind TLS
- `ARATI_WEB_REPORT_DIRECTORY` — Daily close PDF output path
- `ARATI_WHATSAPP_*` — Meta Cloud API credentials (optional)
- `ARATI_WEB_DAILY_CLOSE_ENABLED=0` — Disable internal scheduler (for multi-worker)

---

## 11. Known Limitations (Transparent Disclosure)

1. **Nepali Text Rendering** — Invoice text is English only; Devanagari shaping requires `uharfbuzz`/`raqm` not available on this platform. Bikram Sambat dates print as numbers only.
2. **Discount Model** — Per-invoice only (no per-line discount percentage UI)
3. **No Draft/Hold State** — Invoice is issued when saved (drafts are running folios for stays only)
4. **Single-Process Scheduler** — Daily close runs in-process; multi-worker deployments need external cron
5. **No Expense Tracking** — Operating expenses not recorded; profit/loss not available
6. **Forecasting Disabled** — Requires 90+ business days history + baseline/backtest implementation

---

## 12. Testing & Quality Assurance

- **93 Unit/Integration Tests** — Invoice arithmetic (VAT, service charge, discounts, rounding), Tax vs Bill of Supply, payment status, schema migration, 25-room workflow, daily closing (timezone, idempotency, catch-up), PDF/ESC-POS generation
- **Smoke Test** — Full Tk app boot + screen rendering + permission verification (`xvfb-run`)
- **Web App Tests** — WhatsApp agent flows, webhook parsing, signature verification, duplicate delivery, human handoff

---

## 13. Deliverables for Client

| Artifact | Format | Purpose |
|----------|--------|---------|
| **Application** | Windows EXE / Linux source / Web server | Production deployment |
| **User Manual** | PDF | Staff training |
| **Admin Guide** | PDF | Configuration, daily close, backup/restore |
| **API Documentation** | OpenAPI/Swagger (`/docs`) | Integration reference |
| **Database Schema** | SQL / ERD | Technical handover |
| **Test Report** | pytest output | Quality evidence |
| **Release Archive** | ZIP with checksums | Versioned delivery |

---

## 14. Next Steps & Roadmap (Optional Enhancements)

| Priority | Feature | Effort |
|----------|---------|--------|
| High | Nepali language PDF (Devanagari shaping) | Medium |
| High | Per-line discount % UI | Low |
| Medium | Expense ledger + P&L report | Medium |
| Medium | Multi-property support | High |
| Low | Channel manager integration (Booking.com, etc.) | High |
| Low | Mobile PWA for housekeeping | Medium |
| Low | Guest-facing portal (booking, folio view) | Medium |

---

## Contact & Support

**Developed for:** Arati Hotel, Khandbari-01, Sankhuwasabha  
**System:** Arati Hotel Billing & Management System v1.0.0  
**License:** MIT (based on BilledIn)

---

*This document represents the complete implemented feature set as of the current release. All features are tested and operational in the provided codebase.*