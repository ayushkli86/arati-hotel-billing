# DATABASE_MAPPING

## Local (SQLite, authoritative)
- `rooms` (id, number, type, status, active, nightly_rate, ...)
- `guests` (id, full_name, name, phone, active, ...)
- `stays` (id, room_id, guest_id, status, check_in, check_out, guest_name, ...)
- `invoices`, `invoice_items`, `payments` (local billing authority)
- `kots`, `room_charges` (local KOT and folio charges)
- `catalog_items`, `menu_items` (local menu authority)
- `kot_orders`, `kot_order_items`, `kot_sync_state`, `kot_sync_queue` (additive cloud mirror + bookkeeping)

## Cloud (Supabase Postgres, KOT authority)
- `users` (admin/staff/kitchen)
- `dining_tables` (id, name, zone, seats, is_active)
- `dishes` (id, name, category, price, available, station)
- `kots` (id, number, table_id, waiter, note, status, paid, created_at, closed_at)
- `kot_lines` (id, kot_id, dish_id, name, category, price, qty, station)
- `idempotency_keys`

## Mapping
- Cloud `dining_tables.name` "Room <number>" ↔ local `rooms.number` (stable by number, not id).
- Cloud `dishes` ↔ local `catalog_items` via `menu.map` (local id → cloud id).
- Cloud `kots.id` ↔ local `kot_orders.cloud_kot_id` (unique).
- Cloud `kots.id` → deterministic UUID `order_uuid` (uuid5).
- Local `stays.id` ↔ `kot_orders.local_stay_id`; `rooms.id` ↔ `local_room_id`; `guests.id` ↔ `local_guest_id`.
- Local `invoices.id` ↔ `kot_orders.local_invoice_id` (via local `kots`).
EOF