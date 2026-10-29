# Arati Hotel Billing — Executive Feature Summary
## One-Page Client Presentation

---

### **What It Is**
A **complete hotel property management & billing system** built for Arati Hotel, Khandbari. Runs locally on your hardware — no cloud, no subscription, full data ownership.

---

### **Core Modules**

| Module | Key Capabilities |
|--------|------------------|
| **Front Desk** | Room board (visual grid), check-in/out, reservations, housekeeping, guest directory, stay extensions, room charges |
| **Billing** | Three-column invoice builder, Tax Invoice / Bill of Supply, VAT (13%) + Service Charge (10%), multi-stay folios, draft→issue workflow |
| **Payments** | 7 methods (Cash, Card, eSewa, Khalti, Fonepay, Bank, Room Credit), partial payments, refunds, adjustments, immutable ledger |
| **WhatsApp Orders** | Guest orders food/rooms/services via WhatsApp → staff queue → status updates auto-sent to guest |
| **Reports** | 10+ operational reports (daily/monthly/custom, collections, outstanding, occupancy, cashier) — CSV/PDF/Print |
| **Analytics** | Sales trends, period comparison, category/room/payment breakdowns, room KPIs (ADR, RevPAR, Occupancy), data quality audit |
| **Daily Close** | Automatic midnight closing (Kathmandu TZ), idempotent, catch-up on restart, versioned PDF reports |
| **Staff & Security** | Admin/Staff roles, PBKDF2 passwords, CSRF, login throttling, session versioning, full audit log, staff attendance |
| **Settings** | Hotel identity, invoice config, tax rates, payment methods, printer layout (A4/80mm/58mm), logo, policies |

---

### **Invoice Output Formats**
- **A4 Tax Invoice / Bill of Supply** — Professional, legal-compliant, with amount in words
- **80mm & 58mm Thermal Receipts** — POS printer ready
- **PDF Download / Print Preview / ESC/POS Raw** — All from same calculation engine

---

### **Deployment**
| Option | Use Case |
|--------|----------|
| **Desktop App** | `arati_desktop.py` — Chrome App Mode window, feels like native software |
| **Web Server** | `run_web.sh` — Access from any browser on LAN |
| **Windows EXE** | Standalone installer — no Python needed on client machine |

---

### **Tech Stack**
- **Backend:** FastAPI + SQLAlchemy + SQLite (PostgreSQL ready)
- **Frontend:** Jinja2 + HTMX + Alpine.js + Tailwind CDN
- **Auth:** Signed HTTP-only cookies, PBKDF2, CSRF, rate-limited login
- **Timezone:** Asia/Kathmandu (Bikram Sambat date support)

---

### **Data Integrity**
✅ Additive migrations (never drop data)  
✅ Historical snapshots (rates, tax, totals frozen at creation)  
✅ Soft deletes (guests, rooms, staff deactivated — not deleted)  
✅ WAL mode SQLite (safe concurrent reads)  
✅ Automated backup/restore scripts included  

---

### **Limitations (Transparent)**
- Invoice text: English only (Nepali glyphs need text-shaping engine not on this platform)
- Discounts: Per-invoice only (no per-line % UI)
- No expense tracking / P&L
- Forecasting disabled until 90+ days history + baseline built
- Single-process daily close scheduler

---

### **Testing**
- **93 automated tests** — arithmetic, tax models, migrations, daily close, PDF generation
- **Smoke test** — full app boot + permission verification
- **Web tests** — WhatsApp agent flows, webhook security, duplicate handling

---

### **Delivered With**
- Windows EXE / Linux source / Web server
- User manual + Admin guide (PDF)
- OpenAPI docs (`/docs`)
- Database schema & ERD
- Test report
- Versioned release archive with checksums

---

**Ready for production use at Arati Hotel, Khandbari.**