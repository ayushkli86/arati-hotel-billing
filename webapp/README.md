# Arati Hotel – Khandbari web front office

A separate FastAPI web app for hotel operations. It uses SQLAlchemy with SQLite by default, Jinja2 templates, HTMX for partial updates, Alpine.js for the payment dialog, and Tailwind CSS from its CDN. The existing Tk desktop application and database are not changed by this app.

## Start locally

From the repository root:

```bash
python -m venv .venv-web
source .venv-web/bin/activate
pip install -r webapp/requirements.txt
python -m webapp.seed
uvicorn webapp.main:app --reload
```

Open <http://127.0.0.1:8000/billing/create> for Create Invoice (or <http://127.0.0.1:8000> for the dashboard). From the repository root, `./run_web.sh` performs these setup steps and starts the server. Demo accounts:

- Admin: `admin` / `admin123`
- Staff: `frontdesk` / `staff123`

On Windows, double-click `run_web.bat` to set up and open the web front office. To point the Start Menu's **Arati Hotel Billing** shortcut at the web app from a source install, run `.\scripts\create_web_shortcut.ps1` in PowerShell. The shortcut opens the Room Board; running `run.bat` directly still launches the desktop till.

Change these demo passwords before using a non-demo installation. Seed data is idempotent and is written to `webapp/data/arati_web.db` by default.

## Configuration

- `ARATI_WEB_DATABASE_URL`: SQLAlchemy URL. Defaults to the local SQLite database; PostgreSQL URLs work with the matching SQLAlchemy driver installed.
- `ARATI_WEB_SECRET`: long random signing key for session cookies. Always set this outside development.
- `ARATI_WEB_HTTPS=1`: enables secure-only session cookies when served behind HTTPS.
- `ARATI_WEB_REPORT_DIRECTORY`: directory for generated daily-close PDFs; defaults to `webapp/data/reports`.
- `ARATI_WEB_DAILY_CLOSE_ENABLED=0`: disables the in-process daily-close scheduler. It is enabled by default and uses the `close_time` hotel setting (default `00:05`, Asia/Kathmandu).
- `ARATI_WHATSAPP_TOKEN`, `ARATI_WHATSAPP_PHONE_NUMBER_ID`: Meta WhatsApp Cloud API credentials. Without them the assistant runs in simulator mode.
- `ARATI_WHATSAPP_VERIFY_TOKEN`: the private string you also enter in the Meta webhook configuration.
- `ARATI_WHATSAPP_APP_SECRET`: Meta app secret used to verify `X-Hub-Signature-256` on incoming webhooks. Set it in production.
- `ARATI_WHATSAPP_API_VERSION`: Graph API version for outbound messages (default `v21.0`).
- `ARATI_WHATSAPP_ENABLED=0`: stops processing incoming WhatsApp messages; the simulator and Orders page keep working.

## WhatsApp order assistant

The **Order Bookings** page (`/orders`) is the front desk's queue for WhatsApp requests. A guest writes to the hotel number and the assistant runs a numbered menu:

1. **Food & drinks** — items from the Catalog (categories `restaurant`, `food`, or `beverage`), then pickup, delivery, dine in, or delivery to a room.
2. **Book a room** — check-in date, nights, guests, and a room type from the Catalog (`room`) category. This creates a booking request for the front desk to confirm against availability.
3. **Event or service** — any active Catalog item in the `service` category, with a preferred date and time plus optional notes.

A confirmed conversation creates an `ORD-YYYYMMDD-NNNN` order with its items and an estimated total. Staff move it through New → Confirmed → Preparing → Ready → Completed, or cancel it; each change is audited and sends a WhatsApp update to the guest. Choosing “Talk to the front desk” pauses the assistant for that chat and staff reply from the order page. Orders are requests only — VAT and service charge are applied when the booking is billed.

Without Cloud API credentials the same agent runs in the **simulator** on the Orders page: messages and orders are stored locally, but nothing leaves the server. The simulator is a good way to train staff and to test menu changes.

### Connect the hotel's WhatsApp number

1. Create a Meta developer app with the WhatsApp product and register the hotel's business number.
2. Generate a permanent access token and copy the WhatsApp phone number ID.
3. Set `ARATI_WHATSAPP_TOKEN` and `ARATI_WHATSAPP_PHONE_NUMBER_ID` in the server environment.
4. Choose a private `ARATI_WHATSAPP_VERIFY_TOKEN`, then in Meta → WhatsApp → Configuration set the callback URL to `https://your-host/webhooks/whatsapp`, enter the same verify string, and subscribe to **messages**.
5. Set `ARATI_WHATSAPP_APP_SECRET` so unsigned webhook payloads are rejected, then restart the web server.

The Orders page shows the exact webhook URL and whether each setting is present. The webhook must be reachable from the internet, so a local development server needs a tunnel. Keep tokens and the app secret in the process manager or secret store, never in source control.

The agent reads menu items, room types, and services from **Catalog**. Keep the relevant items active and give each one the category the assistant expects.

For example, generate a session key with `python -c 'import secrets; print(secrets.token_urlsafe(48))'` and provide it through your process manager or secret store. Run behind an HTTPS reverse proxy in production. Tailwind, HTMX, and Alpine load from public CDNs, so production deployments should pin and self-host these assets if offline operation or a strict content security policy is required.

The built-in daily-close worker is intended for a single scheduler-enabled application process. In a multi-worker deployment, enable it on only one worker (or disable it everywhere and run an external scheduler) to avoid duplicate simultaneous report attempts.

## Implemented pages

- Dashboard with Kathmandu business date, sales and occupancy metrics, occupancy progress, room status filters, sorted balances, modal collection, recent invoices, and quick actions. Sales details add Today/7/30/90-day trends, room KPIs, category/room/payment charts, a data-quality review panel, and an explicit forecast-readiness note.
- WhatsApp Order Bookings page with a request queue, type/status/search filters, and a built-in assistant simulator. Orders record food, room, and service requests with items, fulfilment, room/delivery details, guest contact, and staff notes; a detail page advances the status, sends the guest a WhatsApp update, shows the conversation, and accepts manual replies.
- Room board with status counts, filters, live search, cards/list views, check-in, reservation, checkout confirmation, housekeeping actions, and folio links. Reservations retain guest contact snapshots, expected dates, nightly rate, deposit, notes, and reject overlapping stays/bookings; check-in carries the reserved guest details and rate into the stay. The reservation ledger filters by status, room, and dates, and supports audited cancellation with a reason; recorded deposits remain visible for separate refund reconciliation. Room inventory assigns rooms to catalog room types; type-rate changes update linked rooms unless a room has a custom override. Guest directory with profile editing, administrator deactivation, and invoice history; invoice search/status filters; a three-column invoice workspace with multi-item billing and 13% VAT; draft/issue/print actions; PDF download; payment ledger; daily report summary; and staff/system navigation destinations.
- PBKDF2 password verification, signed HTTP-only session cookies, and CSRF tokens on state-changing forms.
- Admin-only Staff Accounts page for creating, editing, disabling, and safely deleting user accounts, including role and password management. Users flagged for a required password update must set a 12-character password before accessing the workspace. Accounts referenced by transaction or audit history are retained and should be disabled instead.
- Admin-only Hotel Settings page for hotel identity, invoice prefix, VAT/service-charge rates, language/copy/payment defaults, configurable comma-separated payment methods, date format, logo, policy, and footer; settings feed new invoices, room checkouts, collection/refund forms, payment filters, and printed invoice details.
- Admin-only Printer Settings page for A4/80 mm/58 mm output, page margins, copy count, preview/direct workflow, and printed header/footer/contact/tax sections; includes a non-persisted test invoice. Invoice history provides a separate thermal receipt reprint using the configured roll width (or 80 mm when A4 is selected). Physical printer selection and silent printing remain controlled by the browser and operating system.
- Save & Print commits the invoice before opening its print view, which confirms the saved invoice number and provides invoice history, PDF download, and print actions. Issued invoices can be shared with a prefilled email or WhatsApp message and attached PDF through the device's Web Share API when supported; browsers without file sharing open the message composer and download the PDF for manual attachment. The guest email and phone are used as the suggested recipients.
- Reports for daily/monthly sales, custom ranges, collections, receivables, refunds, cashier sales, occupancy, room revenue, and operations, with date presets, filters, CSV/PDF export, and print.
- Admin-only Sales Analysis with daily/weekly/monthly trends, collection and discount ratios, room/category/cashier breakdowns, refunds, and optional period comparisons. Dashboard Sales Details remain available to front-desk staff.
- Versioned daily-close PDFs, administrator generation/regeneration, authenticated PDF download, audit history, scheduler run history, and automatic catch-up after downtime.
- Mobile KOT JSON API for the Flutter app in `arati_kot_mobile/`: `GET /api/rooms` (rooms with a checked-in guest), `GET /api/menu` (active restaurant items), and `GET /api/kots` (open tickets from every device), each returning the session CSRF token alongside the rows. `POST /mobile/kot/save` writes the ticket (`mode: "room"` posts the items to that room's folio; `mode: "walkin"` takes `guest_name`/`table_number` for an individual and charges nothing to a room, for payment at the counter); `POST /api/kots/{id}/cut` marks it ready and `POST /api/kots/{id}/status` moves it to preparing/ready/served (`428` when the second confirmation is still required, `409` when another device changed it). `POST /api/kots/{id}/delete` removes a ticket and reverses its room charges (`428` without `confirm: true`, `409` once the ticket has reached an invoice). All of them answer `401` with `{"detail": ...}` to a signed-out client instead of redirecting to `/login`, so send `Accept: application/json`.

The Flutter app finds the server again after the Wi-Fi or IP changes. On launch (and on a failed request) it tries the last address, the `arati.local`/`debian.local` mDNS names, the `_arati-kot._tcp` service, and finally scans the phone's own `/24` for port 8000. The login screen shows the resolved address; tap it to enter an address manually or press the refresh icon to search again. Only port 8000 needs to be reachable on the host, so keep the web server on `0.0.0.0:8000` and the firewall open for the Wi-Fi interface. Avoid running Tailscale with its default netfilter mode on a LAN that uses the `100.64.0.0/10` range (some hotel/carrier Wi-Fis do): its spoofing guard drops all such LAN traffic, so run `sudo tailscale set --netfilter-mode=off` on that host.

The web database is intentionally isolated from the desktop application's existing schema. This keeps deployment reversible and avoids accidental writes to live desktop data while the web workflows are being introduced.

## Tests

```bash
.venv-web/bin/pip install pytest
.venv-web/bin/python -m pytest tests -q
```

The suite covers the WhatsApp agent's food, room and service flows, invalid input recovery, human handoff, duplicate webhook delivery, status notifications, webhook parsing, phone normalization and signature verification.
