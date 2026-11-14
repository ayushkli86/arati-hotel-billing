# Cloud KOT sync

The hotel's front-office webapp (FastAPI + SQLite) and the kitchen app
(Flutter + Render + Supabase) are two separate systems. This integration lets
them see each other's work without either one giving up its own database.

- **Local webapp** keeps owning billing, receipts, rooms, folios and the admin
  menu.
- **Cloud app** keeps owning kitchen tickets and kitchen status.
- **Local pulls** cloud tickets into additive `kot_*` tables so the desk can see
  what the kitchen is doing.
- **Local pushes** KOTs cut in the webapp and menu edits to the cloud, so both
  apps show the same orders.
- **Nothing is migrated.** SQLite stays SQLite, Supabase stays Supabase, and the
  local machine never listens on a public port: all traffic is outbound HTTPS.

```
Flutter / kitchen app ──▶ Render (arati-kot, FastAPI) ──▶ Supabase Postgres
                                    ▲
                                    │ outbound HTTPS only
                                    │
                        Arati webapp (FastAPI + SQLite)
                        └─ webapp/integrations/kot/
```

## Ownership rules

| Data | Authoritative side | Direction |
| --- | --- | --- |
| Kitchen status (pending/preparing/ready/served/cancelled) | Cloud | cloud → local |
| Payment status of a cloud ticket | Cloud | cloud → local |
| Menu items, prices, availability | Local admin | local → cloud |
| Hotel rooms (number, type) | Local | local → cloud (as selectable tables) |
| Invoices, payments, folios, GST | Local | never leaves the machine |
| Local KOT numbers | Local | copied into the cloud ticket's note/waiter |

Consequences worth remembering:

- The cloud never creates, edits or deletes local invoices. A cloud ticket is
  only linked to a local invoice when a local KOT is already attached to it,
  and each link writes an `AuditLog` row (`action = kot.billing_link`,
  `username = kot-sync`).
- Deleting a menu item locally does **not** delete the dish in the cloud app.
  The integration only creates and updates.
- Editing a ticket's status on the local dashboard does not push a status
  backwards to the kitchen. Local edits to cloud mirrors are overwritten by the
  next pull, on purpose.

## Tables added to SQLite

Created automatically by the normal `Base.metadata.create_all` startup path.
They are new tables only; no existing table is altered.

| Table | Purpose |
| --- | --- |
| `kot_orders` | One row per cloud ticket (`cloud_kot_id` and `order_uuid` unique) |
| `kot_order_items` | Ticket lines, unique per `(order_id, position)` |
| `kot_sync_state` | Key/value cursors: `kots.cursor`, `menu.map`, `sync.last_run_at`, `sync.last_error` |
| `kot_sync_queue` | Outbound jobs with `dedupe_key`, `status`, `attempts`, `last_error` |

## Cloud side

The Render service is `arati-kot` (`srv-dbs4a5u7bikc73eifto0`,
<https://arati-kot.onrender.com>) built from `ayushkli86/kot-mobile`. It shares
the same Supabase project as the Android app, so a ticket cut on either client
appears in both. Its environment already contains `KOT_DATABASE_URL`,
`KOT_SECRET_KEY`, `KOT_CORS_ORIGINS`, `KOT_CURRENCY=Rs`,
`KOT_RESTAURANT_NAME=Arati Hotel`, `KOT_SEED_DEMO=false`.

Health check used by Render: `GET /api/health`.

### Create the service account

1. Open the cloud app and sign in as the hotel admin.
2. Create a user named `kot-sync` with role **admin** (menu pushes use the
   admin-only dish endpoints) and its own password.
3. Do not reuse a real person's login: the account shows up in the cloud audit
   trail for every mirrored order.

## Local configuration

Copy the template and fill it in:

```bash
cp .env.kot-sync.example .env
# edit KOT_CLOUD_URL / KOT_CLOUD_USERNAME / KOT_CLOUD_PASSWORD
```

Then either export the variables or let uvicorn read the file:

```bash
set -a && . ./.env && set +a && ./run_web.sh
# or
.venv-web/bin/python -m uvicorn webapp.main:app --host 127.0.0.1 --port 8000 --env-file .env
```

**Run one worker only.** The poller is a single in-process asyncio task guarded
by a lock. Two uvicorn workers would mean two pollers fighting over the cursor;
`run_web.sh` already runs a single worker, so use it.

Restart the webapp after changing any `KOT_*` value.

## What a cycle does

Every `KOT_POLL_SECONDS` (default 60s, first run ~3s after startup):

1. **Pull** — reads `/api/kots?since_id=<cursor>` page by page, upserts each
   ticket and its lines, then commits the cursor in the same transaction. A
   crash mid-cycle replays from the last committed cursor, never further.
2. **Refresh open tickets** — the newest `KOT_OPEN_REFRESH_LIMIT` tickets that
   are still pending/preparing/ready are re-fetched so status changes land even
   if the cursor already passed them.
3. **Queue local work** — local `Kot` rows in `KOT_PUSH_ORDER_STATUSES` that are
   not yet mapped are queued (`kot:<id>`), catalog changes are compared with
   the cloud menu (`menu.map`), and active hotel rooms are mirrored as cloud
   tables named `Room <number>` (`rooms.map`).
4. **Flush the queue** — sends each job with an `Idempotency-Key`, retries up to
   5 times with exponential backoff, and marks the job `failed` (never deletes
   it) when it gives up. Successful order pushes store `cloud_kot_id` on
   `kot_orders`, so the same local KOT is never created twice.
5. **Link billing** — attaches `local_invoice_id`/`local_invoice_number` when a
   mirrored ticket points at a billed local KOT, and writes the audit row.

Failures never block the desk: the webapp keeps serving billing and the local
kitchen screen whether or not the cloud is reachable.

## Dashboard

**System → Cloud KOT Sync** (`/kot-integration`, admin only) shows:

- connection state, cloud URL and service account (never the password),
- open tickets, today's tickets, queued outbound jobs, failed jobs,
- last successful cycle, ticket cursor, unbilled mirrored tickets,
- the 20 most recent tickets with kitchen/payment status and invoice number,
- the last 10 failed events with their error text,
- a **Sync now** button (CSRF-protected) that wakes the poller immediately.

## Monitoring

- Render: `GET /api/health` from the dashboard and Render's own health check.
- Local: the dashboard's *Last successful cycle* and *Last sync error*.
- Logs: logger `webapp.kot_sync` (`INFO` per cycle summary, `WARNING` per failed
  job, `ERROR` for a broken cycle). Credentials and tokens are never logged.
- A stale *Last successful cycle* older than a few poll intervals with a clean
  network means the poller is not running — restart the webapp and check the
  startup log line.

## Rollback

The integration is additive and optional, so rolling back is configuration, not
data surgery:

1. Set `ARATI_WEB_KOT_SYNC=0` (or remove the `KOT_*` variables) and restart.
   The poller does not start; the dashboard shows "Not configured"; billing,
   receipts, rooms and the local kitchen display behave exactly as before.
2. To keep the mirror but stop outbound writes, set `KOT_PUSH_MENU=0` and
   `KOT_PUSH_ORDERS=0`.
3. To drop the mirror entirely, stop the webapp and drop the four `kot_*`
   tables. They hold no accounting data, so nothing else is affected — take a
   backup of `webapp.db` first anyway.
4. On the cloud side nothing has to change: the integration only ever creates
   and updates tickets and dishes through the public API.

## Tests

All offline, against in-memory SQLite and a fake cloud client — the production
database is never touched:

```bash
.venv-web/bin/python -m pytest tests/test_kot_sync.py tests/test_kot_client.py tests/test_kot_integration_page.py -q
```

Covered: first pull and cursor commit, idempotent re-pull, restart from the last
committed cursor, cloud-authoritative status/payment, room vs table orders,
line replacement that preserves local links, queue dedupe, push with mapping,
retry then give-up after five failures, menu create/update with no deletes,
billing link plus audit, disabled configuration, dashboard snapshot,
client login/token refresh/retry/validation, and the page's admin-only gate.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Dashboard says "Not configured" | Missing URL or service account | Set the three `KOT_*` values and restart |
| `Invalid credentials` in *Last sync error* | Wrong `KOT_CLOUD_USERNAME`/`KOT_CLOUD_PASSWORD` | Fix the env, restart |
| First cycle takes ~30s | Free Render instance was asleep | Expected; the client retries 5xx |
| Tickets appear twice on the cloud | Two pollers (two workers) | Run a single uvicorn worker |
| Menu edits do not appear in the app | Service account is not admin | Recreate it with the admin role |
| Failed jobs stay `failed` | Five failed attempts (validation or permissions) | Read the error text, fix the cause, then `Sync now` |

## Room and customer resolution

When a cloud ticket is mirrored, the local app resolves it against the hotel
master data:

- `order_type = room` (cloud table name `Room <number>`): look up `rooms.number`.
  - Room missing → `resolution_status = unknown_room`, ticket goes to the
    exception queue, nothing is charged.
  - Room vacant → `vacant`, exception queue.
  - Room's last stay checked out → `checked_out`, exception queue.
  - Active `stays` row found → `resolved`; the stay, guest and room ids are
    stored on `kot_orders`.
- Other order types (`table`, `walk-in`) → `not_room`; no room charge is posted.

Resolved room-service tickets post `RoomCharge` rows to the stay folio exactly
once (`billing_status` flips `pending → billed`). Re-polling never duplicates
charges because only `pending`/`review` tickets are touched.

## Menu validation

`menu.map` (local catalog id → cloud dish id) is reversed during upsert so each
mirrored line records `local_catalog_item_id`, `local_available` and
`price_matches`. Unmapped or disabled items are listed in `menu_issues` and the
ticket appears in the exception queue. Price differences are logged but the cloud
price snapshot is preserved (the cloud ticket is a snapshot of what was ordered).

## Exception queue

`/kot-integration` shows tickets that need review: unknown/vacant/checked-out
rooms, unresolved menu items, or billing failures. Nothing is discarded.
