# KOT_API_MAPPING

## Cloud (Render) endpoints used by local sync
- `POST /api/auth/login` — service account login (username/password).
- `GET /api/health` — connectivity.
- `GET /api/kots?since_id=&limit=` — ascending cursor paging.
- `GET /api/kots/{id}` — refresh open tickets.
- `POST /api/kots` (Idempotency-Key) — push local KOTs.
- `GET /api/dishes`, `POST/PATCH /api/dishes/{id}` — menu reconcile.
- `GET /api/tables`, `POST/PATCH /api/tables/{id}` — room reconcile.

## Local endpoints
- `GET /kot-integration` (admin) — dashboard.
- `POST /kot-integration/sync` (admin, CSRF) — manual wake.

## Auth
- Cloud uses `/api/auth/login` (username/password) → bearer token; refreshed on 401.
- Local uses existing session auth; sync route admin-only.
EOF