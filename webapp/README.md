# Arati Hotel – Khandbari web front office

A separate FastAPI web app for hotel operations. It uses SQLAlchemy with SQLite by default, Jinja2 templates, HTMX for partial updates, Alpine.js for the payment dialog, and Tailwind CSS from its CDN. The existing Tk desktop application and database are not changed by this app.

## Start locally

From the repository root:

```bash
python -m venv .venv-web
source .venv-web/bin/activate
pip install -r webapp/requirements.txt
python -m webapp.seed
python -m webapp.seed_menu   # apply the latest full restaurant menu
uvicorn webapp.main:app --reload
```

Open <http://127.0.0.1:8000/billing/create> for Create Ireceipt (or <http://127.0.0.1:8000> for the dashboard). From the repository root, `./run_web.sh` performs the base setup/start (venv, deps, `webapp.seed`, Uvicorn); run `python -m webapp.seed_menu` afterward when you need the current full menu in the same database. Demo accounts (development):

- Admin: `admin` / `admin123`
- Staff: `frontdesk` / `staff123`

### Windows

1. Install Python 3.11+ with **Add Python to PATH** enabled.
2. Double-click `run_web.bat` from the repository root (first run requires internet to install dependencies).
3. The script stores the virtual environment, database, and generated files under `%LOCALAPPDATA%\AratiHotel\WebBilling`, runs the base seed, and opens the app.

To apply the latest restaurant menu seed against that environment/database, run from the repository root:

```bat
"%LOCALAPPDATA%\AratiHotel\WebBilling\.venv\Scripts\python.exe" -m webapp.seed_menu
```

For a clean/fresh web database, stop the app and remove/back up `%LOCALAPPDATA%\AratiHotel\WebBilling` (or its DB/data) before running `run_web.bat` again. This only affects the web app’s local data.

In production (`ARATI_ENV=production`), `webapp.seed` does not create demo accounts/data unless `ARATI_SEED_DEMO=1`; set `ARATI_INITIAL_ADMIN_USER` and `ARATI_INITIAL_ADMIN_PASSWORD` (>=12 chars) to create the first admin (password change required on first login).

Change demo passwords before using a non-demo installation. Seed scripts are idempotent and use `webapp/data/arati_web.db` by default (or `ARATI_WEB_DATABASE_URL` if set).

## Configuration

- `ARATI_WEB_DATABASE_URL`: SQLAlchemy URL. Defaults to the local SQLite database; PostgreSQL URLs work with the matching SQLAlchemy driver installed.
- `ARATI_WEB_SECRET`: long random signing key for session cookies. Always set this outside development.
- `ARATI_WEB_HTTPS=1`: enables secure-only session cookies when served behind HTTPS.
- `ARATI_WEB_REPORT_DIRECTORY`: directory for generated daily-close PDFs; defaults to `webapp/data/reports`.
- `ARATI_WEB_DAILY_CLOSE_ENABLED=0`: disables the in-process daily-close scheduler. It is enabled by default and uses the `close_time` hotel setting (default `00:05`, Asia/Kathmandu).

For example, generate a session key with `python -c 'import secrets; print(secrets.token_urlsafe(48))'` and provide it through your process manager or secret store. Run behind an HTTPS reverse proxy in production. Tailwind, HTMX, and Alpine load from public CDNs, so production deployments should pin and self-host these assets if offline operation or a strict content security policy is required.

The built-in daily-close worker is intended for a single scheduler-enabled application process. In a multi-worker deployment, enable it on only one worker (or disable it everywhere and run an external scheduler) to avoid duplicate simultaneous report attempts.

## Implemented pages

- Dashboard with Kathmandu business date, sales and occupancy metrics, occupancy progress, room status filters, sorted balances, modal collection, recent ireceipts, and quick actions. Sales details add Today/7/30/90-day trends, room KPIs, category/room/payment charts, a data-quality review panel, and an explicit forecast-readiness note.
- Order request detail page for food, room, and service requests with items, fulfilment, room/delivery details, guest contact, and staff notes; each status change is audited. Orders are requests only — VAT and service charge are applied when billed.
- Room board with status counts, filters, live search, cards/list views, check-in, reservation, checkout confirmation, housekeeping actions, and folio links. Reservations retain guest contact snapshots, expected dates, nightly rate, deposit, notes, and reject overlapping stays/bookings; check-in carries the reserved guest details and rate into the stay. The reservation ledger filters by status, room, and dates, and supports audited cancellation with a reason; recorded deposits remain visible for separate refund reconciliation. Room inventory assigns rooms to catalog room types; type-rate changes update linked rooms unless a room has a custom override. Guest directory with profile editing, administrator deactivation, and ireceipt history; ireceipt search/status filters; a three-column ireceipt workspace with multi-item billing and 13% VAT; draft/issue/print actions; PDF download; payment ledger; daily report summary; and staff/system navigation destinations.
- PBKDF2 password verification, signed HTTP-only session cookies, and CSRF tokens on state-changing forms.
- Admin-only Staff Accounts page for creating, editing, disabling, and safely deleting user accounts, including role and password management. Users flagged for a required password update must set a 12-character password before accessing the workspace. Accounts referenced by transaction or audit history are retained and should be disabled instead.
- Admin-only Hotel Settings page for hotel identity, ireceipt prefix, VAT/service-charge rates, language/copy/payment defaults, configurable comma-separated payment methods, date format, logo, policy, and footer; settings feed new ireceipts, room checkouts, collection/refund forms, payment filters, and printed ireceipt details.
- Admin-only Printer Settings page for A4/80 mm/58 mm output, page margins, copy count, preview/direct workflow, and printed header/footer/contact/tax sections; includes a non-persisted test ireceipt. Ireceipt history provides a separate thermal receipt reprint using the configured roll width (or 80 mm when A4 is selected). Physical printer selection and silent printing remain controlled by the browser and operating system.
- Save & Print commits the ireceipt before opening its print view, which confirms the saved ireceipt number and provides ireceipt history, PDF download, and print actions. Issued ireceipts can be shared with a prefilled email or WhatsApp message and attached PDF through the device's Web Share API when supported; browsers without file sharing open the message composer and download the PDF for manual attachment. The guest email and phone are used as the suggested recipients.
- Reports for daily/monthly sales, custom ranges, collections, receivables, refunds, cashier sales, occupancy, room revenue, and operations, with date presets, filters, CSV/PDF export, and print.
- Admin-only Sales Analysis with daily/weekly/monthly trends, collection and discount ratios, room/category/cashier breakdowns, refunds, and optional period comparisons. Dashboard Sales Details remain available to front-desk staff.
- Versioned daily-close PDFs, administrator generation/regeneration, authenticated PDF download, audit history, scheduler run history, and automatic catch-up after downtime.
- Mobile KOT JSON API for the Flutter app in `arati_kot_mobile/`: `GET /api/rooms` (rooms with a checked-in guest), `GET /api/menu` (active restaurant items), and `GET /api/kots` (open tickets from every device), each returning the session CSRF token alongside the rows. `POST /mobile/kot/save` writes the ticket (`mode: "room"` posts the items to that room's folio; `mode: "walkin"` takes `guest_name`/`table_number` for an individual and charges nothing to a room, for payment at the counter); `POST /api/kots/{id}/cut` marks it ready and `POST /api/kots/{id}/status` moves it to preparing/ready/served (`428` when the second confirmation is still required, `409` when another device changed it). `POST /api/kots/{id}/delete` removes a ticket and reverses its room charges (`428` without `confirm: true`, `409` once the ticket has reached an ireceipt). All of them answer `401` with `{"detail": ...}` to a signed-out client instead of redirecting to `/login`, so send `Accept: application/json`.

The Flutter app finds the server again after the Wi-Fi or IP changes. On launch (and on a failed request) it tries the last address, the `arati.local`/`debian.local` mDNS names, the `_arati-kot._tcp` service, and finally scans the phone's own `/24` for port 8000. The login screen shows the resolved address; tap it to enter an address manually or press the refresh icon to search again. Only port 8000 needs to be reachable on the host, so keep the web server on `0.0.0.0:8000` and the firewall open for the Wi-Fi interface. Avoid running Tailscale with its default netfilter mode on a LAN that uses the `100.64.0.0/10` range (some hotel/carrier Wi-Fis do): its spoofing guard drops all such LAN traffic, so run `sudo tailscale set --netfilter-mode=off` on that host.

While the app is running it polls the open KOTs every four seconds and raises a high-priority **Arati order alert** when a ticket this device has not seen before arrives (one alert per ticket, or one summary when several land together). Android plays a custom three-note bell (`android/app/src/main/res/raw/arati_alert.wav`, kept from the resource shrinker by `res/raw/keep.xml`) with its own vibration pattern on the `arati_orders_v2` channel, so it is easy to tell apart from other apps. The app asks for notification permission after sign-in, and tickets sent from the same device are not re-announced. Alerts are local to the phone, so the app needs to stay running — keep the kitchen device on the charger with the screen timeout disabled.

The web database is intentionally isolated from the desktop application's existing schema. This keeps deployment reversible and avoids accidental writes to live desktop data while the web workflows are being introduced.

## Tests

```bash
.venv-web/bin/pip install pytest
.venv-web/bin/python -m pytest tests -q
```

The suite covers the mobile KOT API (room and walk-in tickets), the room photo gallery, and error handling for missing records and bad input.
