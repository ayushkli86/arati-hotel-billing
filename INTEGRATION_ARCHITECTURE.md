# INTEGRATION_ARCHITECTURE

## Principle
Local SQLite is the hotel master. Cloud (Render + Supabase) is the KOT system.
Local initiates outbound HTTPS only; localhost is never exposed.

## Components
- `webapp/integrations/kot/config.py` — env-driven settings (disabled unless configured).
- `client.py` — async httpx client, auth, retries, validation.
- `sync_engine.py` — pull/push, resolution, billing, menu/room reconcile.
- `poller.py` — single background task, cursor resume, backoff.
- `models.py` — additive `kot_*` tables.
- Dashboard `/kot-integration` (admin) — status, counts, exceptions, manual sync.

## Data flow
Cloud KOT → Supabase → Render API → local poller → `kot_orders` → resolution → `RoomCharge`/exception queue.
Local menu/rooms → queued/pushed → cloud dishes/tables.
Local KOTs → queued → cloud KOTs (with idempotency key).
EOF